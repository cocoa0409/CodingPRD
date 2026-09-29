# Worklog — task_2652_smart_home_interoperability_certification

## Step 1: Create task directory — 2026-09-04T01:35:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2652_smart_home_interoperability_certification` and `.../workspace` (pre-assigned path, index fixed by scenario number 2652; no index scan performed).

## Step 2: Generate scaffold — 2026-09-04T02:49:00.000Z

All three scaffold artifacts for task 2652 are complete and lint-clean.

## Output (`/home/ubuntu/github/CodingPRD/tasks/task_2652_smart_home_interoperability_certification/`)

| File | Lines | Bytes |
|---|---|---|
| `SCAFFOLD.yaml` (§1.0–§1.7) | 3549 | 179638 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8) | 2429 | 162391 |
| `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9) | 5339 | 337330 |

## Linter verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    66
  §1.1 entities declared:     11
  §1.8 instances scanned:     18
  §1.9 instances scanned:     47
  Calls scanned (§1.8+§1.9):  1484

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## What the scaffold contains

- **§1.0–§1.7**: `beyond-expert`, 11 entities, 14 state machines (cyclic; two independent listing axes), 9 calculations (3 dual-variant), 51 priority-ordered validations, 66 endpoints, 59 errors, 7 roles with segregation of duties, 2 OCC rules, immediate consistency, logical clock via `POST /_clock/set_current_utc`.
- **§1.8**: 18 instances — two per each of the 9 §0.5 difficulty rules.
- **§1.9**: 74 instances across all nine claim-extraction sections (47 with full `test_recipe`, 27 `excluded_because` stubs that each cite a §1.8 instance by exact name). Sections closed out this session: `endpoints` (plan supersession, credential issuance + public directory + withdrawal, 4 stubs), `errors` (auth→role→ownership→standing ladder; the five otherwise-unreached error ids), `rbac` (full 20-cell exclusive-operation denial matrix, entity-backed ownership scoping, the segregation lockout following the recorded conformance decider across a revision round), `cross_cutting_complexity_layers` (both OCC rules, version pinning, 2 stubs), `consistency_model` (immediate visibility of cascades and derived fields).

## Verified beyond the linter

- Instance names unique across both design files; no stub carries a `test_recipe`; every stub's `difficulty_instance` resolves by name (I normalized 21 stubs that had been written as `rule / name` down to the bare name the spec requires).
- All 59 catalogued error ids are exercised somewhere in §1.8/§1.9.
- `SCAFFOLD.yaml` carries neither design key; the other two files each have exactly one top-level key.

Defects found and fixed while finishing: `attestation_verified` is not a declared input of `POST /submissions/{submission_id}/security-decision` (8 payloads), `return-for-info` takes `reason` not `note`, one literal `expected_submission_version` (replaced with a non-OCC endpoint for that RBAC denial), a `$.data[0].id` capture unquoted inside a YAML flow mapping, and a `voided_reason` of `SUBMISSION_WITHDRAWN` that the scaffold actually spells `SUPERSEDED_BY_NEW_PLAN` on the withdraw path.

## Step 3: Copy shared files — 2026-09-04T03:33:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes). workspace/ survived Step 2 intact; no rebuild needed.

## Step 4: Generate PRD — 2026-09-04T03:52:00.000Z

The PRD is complete.

## What was done

Finished `/home/ubuntu/github/CodingPRD/tasks/task_2652_smart_home_interoperability_certification/workspace/PRD.md`, generated solely from `SCAFFOLD.yaml` plus `/home/ubuntu/github/CodingPRD/skills/prd-bench-doc-generator/SKILL.md`. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced; no sibling task was consulted. Every write was an appended heredoc or a scripted append — no single large Write, no `pkill`.

Sections added this session: §3.6 Bench Scheduling, Execution and Result Capture; §3.7 Multi-Vendor Plugfests and Interoperability Credits; §3.8 Conformance Review, Security Review and Credential Issuance (including the two-variant readiness score); §3.9 The Consumer Directory, Recertification and Noncompliance Enforcement; §4 Endpoint Definitions (script-generated from the scaffold); §5 Error Code Catalogue (script-generated).

## Hard Contract results

- **Contract 1 — Field-Name Coverage: PASS** (two independent passes). All 135 required identifiers — 113 entity field names, 65 body inputs, 28 query params, 11 path params after dedup — appear verbatim inside backticks. Zero missing. Also confirmed the nested result-line keys (`feature_set_id`, `outcome`, `evidence_hash`, `recorded_at`, `disputed`) and every computed-read output key (`balance_cents`, `counted_session_count`, `counted_line_count`, `on_time_ratio`, `dispute_free_ratio`, `mandatory_passed_cases`, `optional_passed_cases`, `late_session_count`, `score`, `current_utc`, `variant`).
- **Contract 2 — Rule Coverage: PASS**. All 51 validation rungs enumerated in priority order in §2.8; both OCC rules in §2.9 with write endpoint, version input, error id and 412; all 14 state machines with every `from`/`to`/initial state present as a backticked token (0 missing); all 9 calculations with all constant values present literally (0 missing); all enum values from every field constraint present (0 missing); all 59 error ids used in prose and tabulated with statuses matching the scaffold exactly (0 mismatches); all 66 endpoints' side effects covered in §3 narrative or the §4 description column.
- **Contract 3 — §3 Path Purity: PASS** (two passes). Zero backticked tokens in §3 begin with `/`, are a bare HTTP method, or combine method+path.

## Other verifications

- §2.2 is byte-verbatim from `section-2.2-response-structure.md`.
- §4 table: exactly 4 columns, 66 rows (+header/separator). §5 table: exactly 2 columns, 59 rows.
- No fuzzy words, no pseudocode, no operator syntax (`==`, `>=`, `IN {`, `SUM(`, `->`) anywhere — three leaks inherited from scaffold description text were rewritten into prose.
- Fixed four invented identifiers found during verification: `ERR_SECURITY_BASELINE_UNMET` → `ERR_SECURITY_BASELINE_NOT_MET`, `ERR_REVISION_LIMIT_REACHED` → `ERR_REVISION_LIMIT_EXCEEDED`, and `ERR_ROLE_NOT_PERMITTED`/`ERR_OWNERSHIP_VIOLATION` → `ERR_UNAUTHORIZED` (403). Also split the security-decision failure modes correctly between `ERR_SECURE_BOOT_NOT_VERIFIED` and `ERR_SECURITY_BASELINE_NOT_MET`.
- Digit-group spaces ("15 000 cents") normalised to plain integers so every constant is machine-transcribable.

## Final line count: 542

Last 5 lines verbatim:

```
| `ERR_REVISION_LIMIT_EXCEEDED` | 409 |
| `ERR_NO_COMPLETED_SESSIONS` | 409 |
| `ERR_REMEDIATION_DEADLINE_PASSED` | 409 |
| `ERR_LAB_CAPACITY_EXCEEDED` | 409 |
| `ERR_INSUFFICIENT_CREDIT` | 402 |
```

`tail -40` confirms the file ends at a real section boundary — the final row of the §5 error table, complete and not mid-sentence.

**Orchestrator truncation check (per pipeline instruction):** independently verified — PRD.md is 542 lines, top-level sections §1–§5 all present, §5 error table has exactly 59 `ERR_` rows and §4 has 66 endpoint rows, file ends on a complete table row at a real section boundary. No truncation; no regeneration needed. Also grepped PRD.md for `harder than expert`, `beyond-expert`, `scaffold`, `difficulty` — zero hits, so the Step 2 difficulty instruction did not leak into the PRD.

## Step 5 — Unit test generation (test_helpers/ + test_suite/)

Stage 1 complete: `test_helpers/` at the task root, 9 modules / ~2,690 lines, every file
`ast.parse`-clean and the barrel import smoke-checked.

- `constants.py` — roles, clock anchors, enum domains, fee/penalty/readiness/competency numbers.
- `api_errors.py` — all 58 `ERR_*` ids plus the error-id -> HTTP status map, registered with
  `set_error_http_status_map` so `validate_error(resp, ERR_X)` needs no explicit status.
- `test_users.py` — opaque role identities and header builders; entity-backed
  `make_member_headers` / `make_laboratory_headers` thread the real row id.
- `api_client.py` — one method per endpoint in §4 over `GenericApiClient`.
- `types.py` — state-constant vocabulary, `feature()` / `result_line()` shorthands, UTC instant
  arithmetic (`plus_days`, `plus_minutes`, `minutes_between`, `calendar_date`).
- `factories.py` — payload builders with unique-value generators; all money coerced to `int` cents.
- `assertions.py` — round-half-up arithmetic, `expected_certification_fee`,
  `expected_penalty`, ledger/bench-minute invariants, `assert_states`.
- `fixtures.py` — per-entity primitives, `build_specification` / `build_member` /
  `build_laboratory`, the staged `build_program(stage=...)` walker over the 16-stage lifecycle,
  and 17 pytest fixtures.

Arithmetic cross-checked against the design's own expected figures before Stage 2 began:
fee 150000 / 135000 / 185000, penalty (50300, 5030, 55330) and (350000, 122500, 472500),
readiness 85.00 and 68.34, `plus_days` across a month boundary — all matched.

Stage 2 in progress: `test_suite/` at the task root, one file per testing concern, 17 files.
`test_01_dual_variant_scores.py` (395 lines, 7 tests) written as the exemplar and covering both
`dual_variant_calc` instances. The remaining 16 files were delegated one-file-per-author against
a shared brief (`/tmp/task_2652_test_brief.md`) that fixes the design-index-only contract, the
`Design:` tag format, the PRD-first skip filter and chunked-append output discipline.

Verification harness: `/tmp/verify_2652.py` walks `test_suite/`, requires exactly one `Design:`
line per test, resolves every tag against the source yaml (rejecting `excluded_because:` stubs),
greps every `PRD (§x): "..."` citation verbatim against `workspace/PRD.md`, bans skip/xfail and
the word "scaffold", and reports per-instance coverage against the >=2 difficulty / >=1 corner
floor. Baseline run: 63 instances outstanding (16 difficulty, 47 corner), 0 problems.

## Step 6: Generate implementation — 2026-09-04T04:24:00.000Z

Verification pass complete. Final state of the implementation:

## What was verified this pass

**Bench capacity vs. bench-conflict priority pair (rung 38 / rung 49)** — confirmed both fire with the right ids against a `bench_capacity: 1` lab already holding a 600-minute booking:
- non-overlapping second 600-minute window → `409 ERR_LAB_CAPACITY_EXCEEDED` (ceiling 1 × 600 exceeded)
- window 30 minutes after the prior `window_end` → `409 ERR_BENCH_WINDOW_CONFLICT` (60-minute changeover buffer), i.e. the buffer correctly wins over the ceiling per scaffold "PRIORITY PAIR B (lower half)"
- `bench_index: 2` on a 1-bench lab → `400 ERR_INVALID_REQUEST` (rung 6 range)

**Systematic ladder audit (both directions)**, done with an AST walker that resolves error ids transitively through the helper modules and maps every route decorator to its scaffold endpoint:
- Forward (every rung's `applies_to` endpoint reaches that rung's error id): 1 real gap found — rung 34 `ERR_DEVICE_TYPE_MISMATCH` was unreachable on `POST /test-sessions`. Fixed in `routes/test_sessions.py`, inserted between rung 30 and rung 38, and verified live (`device_type: "SENSOR"` against a LIGHTING plan → `422 ERR_DEVICE_TYPE_MISMATCH`; matching `device_type` → `201 SCHEDULED`). The scaffold declares no `device_type` input for this endpoint, so the check is keyed off an optional body field — the only way the PRD §3.6 sentence ("where the session's own device class disagrees with the plan's `device_type`") is testable.
- Reverse (no rung raised on an endpoint outside its `applies_to`): 2 hits, both deliberate and kept — `POST /plugfests` raising `ERR_INVALID_LABORATORY_STATE` (PRD §3.7 requires an AUTHORIZED host lab at creation but names no error id) and `POST /test-plans/{id}/issue` raising `ERR_INVALID_SUBMISSION_STATE` (PRD §3.5 requires the parent submission still be `IN_REVIEW`). Both are PRD-mandated checks with no alternative id; neither can co-occur with its competing rung, so ordering is unambiguous.

**Regression + fresh-boot** — all four smoke scripts pass end to end (closure `3/9/7/2`, supersede→VOIDED + session CANCELLED + lab minutes back to 0, `ERR_MANDATORY_COVERAGE_INCOMPLETE` then `ERR_INSUFFICIENT_PLUGFEST_CREDITS` then FINAL score `"85.00"`, competency 40.00/SUSPENDED, rolling-90d window). A fresh boot on a clean port returns `response_type: array` with 0 items for all 11 collections — no seeding, no persistence. `python3 -m py_compile` clean across all 24 modules. Envelope keys match PRD §2.2 (`limit`/`offset`/`total_count`/`has_more`).

**Process hygiene** — every server was killed by its specific PID (1399745 → 1424541 → 1433179 → 1435438); ports 17652 and 17653 are free and no stray processes remain. No `pkill` was ever issued.

Note for the caller: the only remaining known deviation from the scaffold's literal `applies_to` tables is the two reverse hits above, which are intentional. The clock surface is write-only (`POST /_clock/set_current_utc` is the sole clock endpoint in the 66).

### Stage 2 complete

`test_suite/` — 17 files, 12,498 lines, **213 tests**, all collected by pytest
(`python3 -m pytest test_suite --collect-only -q` → 213 collected, 0 errors).

Coverage against the design indices: every one of the 18 difficulty instances carries >= 2 tests
and every one of the 47 non-stub corner instances carries >= 1 test. The 27 `excluded_because:`
corner stubs were not translated. Final verifier run: 0 coverage gaps, 0 problems — every test has
exactly one resolvable `Design:` tag, every `PRD (§x): "..."` citation is verbatim in
`workspace/PRD.md` **and** lives in the section it cites, no `skip`/`xfail`, no
`validate_error_is_one_of`, no occurrence of the word "scaffold".

| file | tests | concern |
|---|---|---|
| test_01_dual_variant_scores.py | 7 | readiness PROVISIONAL/FINAL and competency ROLLING_90D/LIFETIME |
| test_02_combinatorial_formulas.py | 8 | five-input fee matrix, penalty rounding before the cap |
| test_03_non_linear_state_machines.py | 9 | review loop to the revision ceiling, listing's two axes |
| test_04_transitive_cascades.py | 11 | IP-withdrawal 4 hops, deprecation 3 hops into bench minutes |
| test_05_validation_priority_pairs.py | 8 | rung 25 > rung 50, rung 38 > rung 49 |
| test_06_boundary_precision.py | 10 | readiness exactly 65.00, firmware overlap of exactly 2 |
| test_07_cross_entity_state_dependency.py | 8 | suspended lab blocks start, credential gates publish |
| test_08_resource_temporal_overlap.py | 10 | 60-minute changeover buffer, plugfest calendar-date clash |
| test_09_compensating_invariants.py | 11 | credit escrow round trip, bench minutes back to zero |
| test_10_corner_entities.py | 21 | defaults, required fields, ranges, filters, junctions, 404 ids |
| test_11_corner_state_machines.py | 18 | ratify/retire, tool-access cycle, plugfest close, bubble-up, cascades |
| test_12_corner_calculations.py | 13 | plan closure fixed point, vendor count, bands, ledger variants |
| test_13_corner_validation_order.py | 18 | shape/enum/date/duplicate order, IP-scope and accreditation gates |
| test_14_corner_validation_gates.py | 16 | competency, result lines, participation, coverage, remediation |
| test_15_corner_endpoints_and_errors.py | 16 | plan supersession, issuance/directory/withdrawal, ladder on submit |
| test_16_corner_rbac.py | 15 | role-exclusive ops, entity-scoped identities, security lockout |
| test_17_corner_layers_and_consistency.py | 14 | stale-view guards, pinned fee/plan snapshot, read-after-write |

One Stage 1 fix landed during verification: `factories.test_plan_payload` and
`factories.test_session_payload` are named after their resources, so pytest was collecting them as
test functions in the six modules that import them (220 collected instead of 213). Both now carry
`__test__ = False`.

#### PRD gaps and design/PRD conflicts found while translating (for the record)

Resolved in the PRD's favour; each cost at most one sub-claim, never a whole instance:

1. **§3.2 vs §3.8 on escrow at `REVIEW_COMPLETE`.** §3.2 says `fee_escrowed_cents` is non-zero
   "exactly while its `state` is `SUBMITTED`, `IN_REVIEW` or `RETURNED_FOR_INFO`", yet §3.8 makes
   credential issuance (from `REVIEW_COMPLETE`) require `fee_escrowed_cents == certification_fee_cents`.
   The suite follows §3.8: escrow survives into `REVIEW_COMPLETE`. An implementation reading §3.2
   literally will fail test_15 test_04/test_05.
2. **Conformance decision against a live plan.** §2.8 rung 43 assigns
   `ERR_MANDATORY_COVERAGE_INCOMPLETE` to a plan that is not `COMPLETE`, while §3.8 assigns
   `ERR_INVALID_TEST_PLAN_STATE` to a plan in `DRAFT`/`ISSUED`/`IN_EXECUTION`. Not uniquely derived,
   so that exact call was dropped; the same rung ordering is proved with a submission that has no
   plan at all (only rung 43 speaks to non-existence).
3. **Absent `remediation_days` on `ORDER_REMEDIATION`.** Rung 6 says shape (`ERR_INVALID_REQUEST`),
   §3.9 says "an absent or out-of-range value being refused with `ERR_INVALID_DATE_RANGE`".
   Dropped; the unambiguous cases (present-where-forbidden → `ERR_INVALID_REQUEST`, 400 days →
   `ERR_INVALID_DATE_RANGE`) are asserted instead.
4. **Timestamps.** Several recipes assert `"2026-09-01T00:00:00Z"` string equality, which §2.4's
   mandatory three fractional digits forbids; those assertions compare instants via `same_instant`.
5. **Design recipe errors corrected against the PRD:** `included_feature_set_ids` must be ordered by
   `feature_code` ascending (§3.5), so `[CORE_DIM, CORE_ONOFF]`; the readiness read returns counts
   plus `score`, not ratio fields (§3.8); `recert_trigger_reason` for an overlap-of-3 revision is
   `FIRMWARE_FEATURE_DELTA`, not `FIRMWARE_SECURITY_CHANGE` (§3.9); an `ip-commitment` cannot be
   scoped to a `DRAFT` specification (§3.2), so that setup was reordered.
6. **Non-PRD literals substituted:** `ip_commitment_type: "RAND_REASONABLE_ROYALTY"` →
   `RAND_ROYALTY_BEARING`; the design's non-v4 absent-id literal → `UNKNOWN_UUID`.
7. **One sub-claim skipped outright** (PRD-first filter): `authorized_device_types: ["CAMERA"]` →
   `422 ERR_INVALID_ENUM_VALUE`. §3.3 calls a bad array a shape failure (`ERR_INVALID_REQUEST`) and
   rung 7's enum-typed input list does not name `authorized_device_types`, so the id is not uniquely
   derivable. Every other claim in that instance is asserted.
8. **Non-blocking ambiguity, deliberately unasserted:** rung 1 exempts `POST /_clock/set_current_utc`
   from authentication while rung 2 "applies to every endpoint", so a header-less clock call has no
   derivable outcome. Only the well-defined case (a `Member` refused 403) is asserted.

## Step 5: Generate unit tests (orchestrator record) — 2026-09-04T04:55:00.000Z

Note: the Step 5 subagent appended its own detailed inventory earlier in this file under "## Step 5 — Unit test generation (test_helpers/ + test_suite/)" (line ~96), out of step order because Step 6 finished first. Below is the subagent's returned summary, verbatim.

Step 5 is complete.

## Deliverables (both at the task root, nothing under `workspace/`)

`test_helpers/` — 9 modules, ~2,700 lines: `constants.py`, `api_errors.py` (all 58 `ERR_*` ids + status map registered via `set_error_http_status_map`), `test_users.py` (opaque roles + entity-backed header builders), `api_client.py` (one method per §4 endpoint), `types.py` (state vocabulary, `feature()`/`result_line()`, UTC instant arithmetic), `factories.py`, `assertions.py` (round-half-up money/score arithmetic, `expected_certification_fee`, `expected_penalty`, ledger/bench-minute invariants), `fixtures.py` (`build_program(stage=...)` over the 16-stage lifecycle + 17 pytest fixtures), `__init__.py` barrel.

`test_suite/` — 17 files, 12,498 lines, **213 tests**, plus `conftest.py`. `python3 -m pytest test_suite --collect-only -q` → 213 collected, 0 errors.

## Coverage and audit result

All 18 difficulty instances have ≥2 tests; all 47 non-stub corner instances have ≥1 test; the 27 `excluded_because:` stubs were not translated. A verifier I wrote (`/tmp/verify_2652.py`) reports **0 coverage gaps, 0 problems**: exactly one resolvable `Design:` tag per test, every `PRD (§x): "..."` citation verbatim in `workspace/PRD.md` *and* located inside the section it cites, no `skip`/`xfail`, no `validate_error_is_one_of`, no occurrence of "scaffold". Files were written incrementally; one file per author, 16 authors delegated against a shared brief.

One Stage 1 bug caught during verification: `factories.test_plan_payload` / `test_session_payload` were being collected by pytest as tests in the six modules importing them (220 collected instead of 213); both now carry `__test__ = False`.

## Findings the implementation and Step 7 need to know

1. **§3.2 vs §3.8 contradict each other on escrow at `REVIEW_COMPLETE`.** §3.2 says escrow is non-zero "exactly while" the state is `SUBMITTED`/`IN_REVIEW`/`RETURNED_FOR_INFO`; §3.8 requires `fee_escrowed_cents == certification_fee_cents` at issuance, which happens from `REVIEW_COMPLETE`. The suite follows §3.8 — an implementation reading §3.2 literally will fail `test_15` tests 04/05.
2. **Two error ids are not uniquely derivable and were dropped as sub-claims:** conformance decision against a non-`COMPLETE` plan (rung 43's `ERR_MANDATORY_COVERAGE_INCOMPLETE` vs §3.8's `ERR_INVALID_TEST_PLAN_STATE`), and absent `remediation_days` (rung 6's `ERR_INVALID_REQUEST` vs §3.9's `ERR_INVALID_DATE_RANGE`). Both rung orderings are still proved via unambiguous variants.
3. **Design-recipe errors corrected against the PRD:** closure ids must sort by `feature_code` (`[CORE_DIM, CORE_ONOFF]`); the readiness read returns counts + `score`, not ratio fields; an overlap-of-3 firmware revision sets `FIRMWARE_FEATURE_DELTA`; an `ip-commitment` cannot be scoped to a `DRAFT` specification. Non-PRD literals substituted: `RAND_REASONABLE_ROYALTY` → `RAND_ROYALTY_BEARING`, non-v4 absent-id → `UNKNOWN_UUID`. Timestamp equality is asserted via `same_instant` because §2.4 mandates three fractional digits.
4. **One sub-claim skipped under the PRD-first filter:** `authorized_device_types: ["CAMERA"]` → `422 ERR_INVALID_ENUM_VALUE` (§3.3 calls it a shape failure and rung 7 does not name that field). Also left unasserted: the header-less `POST /_clock/set_current_utc` case, where rung 1's exemption and rung 2's universality conflict.

**Orchestrator checks:** `find workspace -maxdepth 2 -type d -name "test_*"` → no hits, so neither test directory drifted into `workspace/`. Both live at the task root as required. Steps 5 and 6 were launched in a single assistant message, so the implementation generator had physical isolation from `test_suite/`.

## Step 7 — test/fix iteration loop (diagnostic expert)

Two iterations of the 8-round parallel stability sweep (213 tests x 8 concurrent
rounds, per-test-server isolation, setsid-wrapped).

### Iteration 1 — 207/213 in all 8 rounds, 6 deterministic failures (no flakiness)

All six failures were test-artifact bugs; the implementation was not changed.

1. `test_09_compensating_invariants::TestCreditEscrowRoundTrip::test_03` and
   `::test_04` — arithmetic typo. Expected `credit_balance_cents` 835000 after
   SUB2's rejection released its 165000. 655000 + 165000 = 820000, and the same
   test's own `escrowed_credit_cents == 180000` expectation plus the ledger
   identity (purchased 1000000 = balance + consumed + escrowed) both pin 820000.
   The already-passing `test_05` asserts 820000 for the same checkpoint. Fixed
   the constant (and the docstrings) to 820000 in test_suite/.

2. `test_03_non_linear_state_machines::TestListingAxesWalkIndependentlyThenLock::test_09`
   and `test_11_corner_state_machines::TestCaseWithdrawalOrder::test_16` —
   validation-ladder mis-translation. Both publish a listing after a withdrawal
   that ALSO revoked the linked submission's credential, so rung 16 (submission
   state: publication requires `dac_state` ISSUED) and rung 22 (listing state:
   WITHDRAWN cannot publish) are violated together. §2.8: "the first rung whose
   condition is violated decides the response". Assertions corrected from
   ERR_INVALID_LISTING_STATE to ERR_INVALID_SUBMISSION_STATE (exact error_id,
   not weakened to an HTTP-status check).

3. `test_11_corner_state_machines::TestCaseWithdrawalOrder::test_16` — a stray
   extra positional argument (`ERR_INVALID_DATE_RANGE`) had been pasted into a
   `validate_error(..., ERR_INVALID_CASE_STATE)` call, landing in the
   expected-HTTP-status slot. Removed.

4. `test_11_corner_state_machines::TestCaseRemediationPath::test_17` — asserted
   `remediation_days=30` on the NoncomplianceCase response. COMPUTED/INPUT-FIELD
   SILENCE: PRD names `remediation_days` only as an advance-endpoint input
   consumed to derive `remediation_deadline_at` (rungs 6 and 9, §3.9), never as a
   stored or response-visible case attribute, and §3.9's field enumeration at
   case creation omits it. Sub-assertion removed; the `remediation_deadline_at ==
   2026-10-02T12:00:00Z` check that PRD does uniquely determine was kept.

5. `test_10_corner_entities::TestSpecificationSupersessionTarget::test_20` —
   asserted ERR_SPECIFICATION_NOT_FOUND for a dangling
   `supersedes_specification_id` on POST /specifications. UNIQUE-DERIVABILITY
   COLLAPSE: §2.6 enumerates the nine operations body-level reference resolution
   "applies to" and specification creation is NOT among them, so a faithful
   reader may either resolve it (404) or fall through to rung 13's
   RATIFIED/DEPRECATED status requirement (409). Sub-assertion removed under the
   partial-coverage rule; the DRAFT-target 409, the accepted-successor and the
   reverse-filter assertions all stayed.

### Iteration 2 — 213/213 in all 8 rounds

Clean sweep. No implementation change was needed in either iteration.

### Adjudicated, no change required

- §3.2 vs §3.8 escrow at REVIEW_COMPLETE: §3.2's "non-zero exactly while
  SUBMITTED / IN_REVIEW / RETURNED_FOR_INFO" cannot be the operative rule,
  because the same paragraph enumerates the ledger-moving events (purchase,
  escrow at first submit, release on rejection or withdrawal, consumption at
  issuance) and none of them fires on the IN_REVIEW -> REVIEW_COMPLETE bubble-up.
  Zeroing escrow there would also make §3.8's issuance precondition
  (`fee_escrowed_cents == certification_fee_cents`) unsatisfiable. The
  implementation carries escrow through REVIEW_COMPLETE, which is correct.
- The optional `device_type` body field on POST /test-sessions traces to verbatim
  PRD prose (§3.6 "where the session's own device class disagrees with the plan's
  `device_type` the booking is refused with `ERR_DEVICE_TYPE_MISMATCH`", and rung
  34). It is permissive (fires only on an explicitly supplied mismatching value)
  and no test exercises it. Left in place.

## Step 7: Run tests and iterate — 2026-09-04T05:20:00.000Z

Clean sweep achieved.

## Summary

**Iterations run:** 2

**Final sweep (all 8 `results.$i.json` on disk, written 05:15):**
```
round 1: 213 / 213   failed=0  errors=0
round 2: 213 / 213   failed=0  errors=0
round 3: 213 / 213   failed=0  errors=0
round 4: 213 / 213   failed=0  errors=0
round 5: 213 / 213   failed=0  errors=0
round 6: 213 / 213   failed=0  errors=0
round 7: 213 / 213   failed=0  errors=0
round 8: 213 / 213   failed=0  errors=0
```

Iteration 1 was 207/213 with the **same 6 failures in all 8 rounds** — fully deterministic, zero flakiness, so no load-induced or timing-sensitive defects existed. All six traced to the test artifact; **no change was made to `workspace/implementation/` at all.**

**Tests deleted / sub-assertions removed (PRD-silence category):**
- `test_10_corner_entities.py::TestSpecificationSupersessionTarget::test_20` — the dangling-`supersedes_specification_id` block. **UNIQUE-DERIVABILITY COLLAPSE**: §2.6 enumerates the nine operations body-level reference resolution "applies to" and specification creation is not among them, so a faithful reader may resolve it (404) or fall through to rung 13's RATIFIED/DEPRECATED requirement (409). Removed under the partial-coverage rule; the DRAFT-target 409, accepted-successor and reverse-filter assertions were kept. Scaffold rule: `Corner/entities/specification_supersession_target_must_be_ratified_first`.
- `test_11_corner_state_machines.py::TestCaseRemediationPath::test_17` — the `remediation_days=30` response-field assertion. **COMPUTED/INPUT-FIELD SILENCE**: PRD names `remediation_days` only as an advance-endpoint input consumed to derive `remediation_deadline_at`; §3.9's case-field enumeration omits it. The `remediation_deadline_at == 2026-10-02T12:00:00Z` check was kept. Scaffold rule: `Corner/state_machines/case_remediation_suppresses_then_remediates_and_needs_a_republish`.

**Fixes applied to `test_suite/`:**
- `test_09_compensating_invariants.py` — `TestCreditEscrowRoundTrip::test_03`/`test_04`: `835000` → `820000`. Plain arithmetic typo; 655000+165000=820000, and the test's own `escrowed_credit_cents == 180000` plus the ledger identity (purchased 1000000) both pin 820000 — as does the already-passing `test_05` on the identical checkpoint.
- `test_03_non_linear_state_machines.py::test_09` and `test_11_corner_state_machines.py::test_16` — publish-after-withdrawal assertions changed `ERR_INVALID_LISTING_STATE` → `ERR_INVALID_SUBMISSION_STATE`. The withdrawal also revokes the credential, so rung 16 and rung 22 are violated together and §2.8 gives the response to the earlier rung. Exact error_id preserved, not downgraded to a status check.
- `test_11_corner_state_machines.py::test_16` — removed a stray extra positional argument (`ERR_INVALID_DATE_RANGE`) that had been pasted into a `validate_error(..., ERR_INVALID_CASE_STATE)` call, where it landed in the expected-HTTP-status slot.

**Fixes applied to `test_helpers/`:** none — the fixtures/factories were sound (money already integer cents).

**Fixes applied to `implementation/`:** none.

**Two adjudications from the context note, both resolved in the implementation's favour:**
- The §3.2 vs §3.8 escrow contradiction resolves toward §3.8: §3.2's own enumeration of ledger-moving events (purchase, escrow at first submit, release on rejection/withdrawal, consumption at issuance) contains no event firing on `IN_REVIEW → REVIEW_COMPLETE`, and zeroing escrow there would make §3.8's issuance precondition unsatisfiable. The implementation carries escrow through `REVIEW_COMPLETE`, which is correct.
- The optional `device_type` field on `POST /test-sessions` traces to verbatim §3.6 prose and rung 34, is permissive, and no test exercises it. Left in place.

Storage hygiene verified: in-memory dicts only, no sqlite/file/`/tmp` persistence, nothing seeded at startup, logical clock defaults to `2026-08-01T00:00:00.000Z`.

**Orchestrator verification (per memory: a Step 7 agent can claim a clean sweep with no artifacts on disk):** independently re-read all 8 `results.$i.json` with a fresh `json.load` — every round reports `passed=213 total=213 failed=0 errors=0`, all 8 files present, mtime 05:15. Confirmed.

**Step 8 gating decision:** Step 7 reports 0 `implementation/` fixes but NON-zero test artifact churn (2 sub-assertion deletions + 4 `test_suite/` fixes) and two explicit PRD-ambiguity adjudications (§3.2-vs-§3.8 escrow contradiction; the `ERR_INVALID_SUBMISSION_STATE` vs `ERR_INVALID_LISTING_STATE` rung-precedence question). The skill's skip condition requires 0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes — it is not met here. Step 8 therefore RUNS: those four sites are exactly the places where PRD.md failed to uniquely determine behaviour the implementation had already chosen, which is what PRD_FINALIZED.md exists to pin.

## Step 8: Finalize PRD — 2026-09-04T05:26:00.000Z

Done. `PRD_FINALIZED.md` written with four surgical inline edits.

**Line counts:** PRD.md 542 → PRD_FINALIZED.md 542 (0.0% delta; all four edits are in-line within existing paragraphs). Verified: §1–§5 all present, §5 error table has 59 `ERR_` rows, §4 has 66 endpoint rows, diff touches exactly 4 lines.

**Changes**

- §3.2 — revise — escrow window widened to include `REVIEW_COMPLETE`, with the note that no ledger event fires on `IN_REVIEW → REVIEW_COMPLETE` so the escrow is carried across it unchanged (resolves the §3.2/§3.8 contradiction in the implementation's favour) — `implementation/routes/submissions.py:205-218` (`_resolve_primary_axis` writes `fee_escrowed_cents=0` only on `REJECTED`), `:321` (issuance requires `fee_escrowed_cents == certification_fee_cents`).
- §3.1 — insert — a `supersedes_specification_id` that resolves to nothing is *not* a 404; it fails the same RATIFIED/DEPRECATED requirement and yields `ERR_INVALID_SPECIFICATION_STATE` — `implementation/routes/specifications.py:36-40`.
- §3.6 — insert — `POST /test-sessions` accepts an optional `device_type` string; it is a coherence-check input only, never stored on the session, and omitting it is normal — `implementation/routes/test_sessions.py:64-67`, `:82-96`.
- §3.9 — insert — `remediation_days` is an input only, consumed to derive `remediation_deadline_at` and never stored on the case — `implementation/routes/cases.py:115-118`, `implementation/cascade.py:179-197`.

**No PRD edit for** the `835000 → 820000` arithmetic fix, the stray-positional-argument fix (both pure test bugs), or the publish-after-withdrawal `ERR_INVALID_SUBMISSION_STATE`: §2.8 rung 16 already sits above rung 22 and §3.9's publication paragraph already lists the `dac_state` requirement before the listing-status requirement, matching `routes/listings.py:86-93`.

**Per-edit pre-edit search log**

1. §3.2 escrow window. (a) Subject: `fee_escrowed_cents` lifecycle and the member ledger identity. (b) Enumerated/read: `routes/submissions.py` submit (first submit sets escrow; resubmit deliberately does not), `_resolve_primary_axis` (zeroes on `REJECTED` only), `issue-credential` (`:321` precondition, `:336-339` consume), `withdraw` (`:351` zeroes), `cascade.release_escrow` (defined, and grep confirms it is never called — release happens via `recompute_member`), `cascade.recompute_member`, `calc.member_escrow_cents` (sums `fee_escrowed_cents` over *all* the member's submissions with no state filter), `calc.credit_ledger` (AVAILABLE/COMMITTED variants). (c) Adjustment: phrased the addition as "no ledger event fires on this transition" rather than "escrow is set/kept at the fee", so it stays true for `member_escrow_cents`'s unfiltered sum and for the `AVAILABLE`/`COMMITTED` divergence, and does not imply a new write.
2. §3.1 dangling supersedes. (a) Subject: every read/write of `supersedes_specification_id`. (b) Enumerated by grep across all `.py`: only `routes/specifications.py:28,36-40,52` (create) and `:74,81` (list reverse filter, exact match, unaffected by danglingness); confirmed §2.6's nine body-resolution operations in the impl (`common.body_fk` callsites) do not include specification creation. (c) Adjustment: tied the sentence to §2.6's existing enumeration instead of adding a new rule, and said "fails this same status requirement" so rung 13 needs no rewording.
3. §3.6 optional `device_type`. (a) Subject: the session's device class as input, as stored state, and as filter. (b) Enumerated: `routes/test_sessions.py:64-67` (only reader; compares only when `isinstance(str)`), `:82-96` `new_row` (no `device_type` key), `:108-126` list filters (no `device_type`), `routes/test_plans.py:44,50,60-62`, §2.3's session filter list, §2.8 rungs 7 and 34. (c) Adjustment: deliberately did **not** claim enum validation for this field (the impl does not enum-check it here), and scoped the wording to a "string" input so a non-string payload stays under-determined rather than falsely pinned.
4. §3.9 `remediation_days`. (a) Subject: `remediation_days` as input vs persisted case field. (b) Enumerated by grep: `routes/cases.py:84-101,118` (the only occurrences), `cascade.make_case:179-197` (no such field), `serial.public` (serializes the raw row), case list filters `:60-73`. (c) Adjustment: limited the sentence to the not-stored fact and left the existing (separate) claim about the error identifier for an absent value untouched.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` yields exactly 8 diff lines (4 changed line-pairs), both files are 542 lines, and §1–§5 headings are all intact in PRD_FINALIZED.md. Confirmed minimal-patch discipline.

## Step 9: Complete PRD — 2026-09-04T06:05:00.000Z

Run as **three sequential file-partitioned passes** over `implementation/` rather than one monolithic scan, so that no region of the 3,256-line implementation went unaudited and no pass had to hold the whole codebase in context at once. Each pass edited `workspace/PRD_COMPLETED.md` in place; pass 1 created it from `PRD_FINALIZED.md`, passes 2 and 3 were explicitly instructed not to overwrite it and were handed the list of pins their predecessors had already made, so their partitions do not overlap or re-litigate each other.

Partition:
- **Pass 1** — `app.py`, `middleware.py`, `common.py`, `response.py`, `serial.py`, `errors.py`, `enums.py`, `shape.py`, `queries.py`, `db.py`, `routes/clock.py`, `routes/specifications.py`, `routes/feature_sets.py`, `routes/members.py`, `routes/laboratories.py`
- **Pass 2** — `routes/test_plans.py`, `routes/test_sessions.py`, `routes/plugfests.py`, plus the `calc.py` functions those reach (`plan_closure`, `session_minutes`, interop ratio, counted/late session tallies)
- **Pass 3** — `routes/submissions.py`, `routes/listings.py`, `routes/cases.py`, all of `cascade.py`, plus the remaining `calc.py` (`certification_fee_cents`, `credit_ledger`, `penalty`, `competency`, readiness and its variants)

### Pass 1 result

Source `PRD_FINALIZED.md` 542 lines / 133,534 chars → `PRD_COMPLETED.md` 542 lines / 140,782 chars (+7,248). 18 lines changed, all in-place paragraph replacements. **16 ambiguity-pins, 2 mismatch-revisions.**

Notable: §2.1 empty/whitespace auth header counts as absent but a *supplied* non-`ProgramAdmin` role on the clock endpoint gets 403 not 401 (`middleware.py:39-56`); `api_request_id` is `req_` + 20 uppercase-alphanumerics; `api_request_timestamp` is the **host wall clock**, not the logical clock (`response.py:16-20`); `created_at` ties broken by a store-wide monotonic insertion sequence (`db.py:150-153`); exactly which query filters are enum-validated (422) vs opaque strings that simply match nothing (`shape.py:145-169`); OCC is compare-and-set with **one `version` increment per row per accepted request** and a row created by a request stays at version 1 (`db.py:87-147`); rung 3 ownership applies only to `Member`/`TestLaboratory` and outranks path existence; rung 6/7 shape-vs-enum split (null/bool/absent-body/undeclared-field/code-array rules, enum inputs are strings first). Mismatches: §3.3 a device-class entry outside the five values yields `ERR_INVALID_ENUM_VALUE` not `ERR_INVALID_REQUEST` (`routes/laboratories.py:25-28`); §5's claim to catalogue "every error identifier the service can return" was false — `ERR_NOT_FOUND` (404/405) and `ERR_INTERNAL` (500) sit outside the catalogue and the ladder (`app.py:50-70`).

### Pass 2 result

542 lines / 140,782 → 542 lines / 148,414 chars (+7,632). 23 Edit calls. **18 ambiguity-pins, 5 mismatch-revisions.**

Mismatches: rung 13 for plugfest creation requires `RATIFIED` exactly, not `RATIFIED`-or-`DEPRECATED` (`routes/plugfests.py:48`); the non-object-body rule cannot fire on the 12 body-less POSTs, which never read the body; §3.5 ¶295's "all four of the following hold" listed only three (the fourth is the plan still being `IN_EXECUTION`, `cascade.py:42`); the optional `device_type` on `POST /test-sessions` is exempt from rungs 6 and 7 — a bogus class string yields `ERR_DEVICE_TYPE_MISMATCH`, not `ERR_INVALID_ENUM_VALUE`; §3.8's effective-outcome tie-break is `recorded_at` → session `created_at` → session insertion seq → line index, not line-position-then-created_at (`calc.py:119-121`).

Notable pins: the parent submission's unconditional `version` bump on plan issuance is the one place §2.4's no-change rule is set aside, verified unique across all three `touch()` callsites (`routes/test_plans.py:60`); `session_type` is descriptive only and gates nothing; a stored result line carries exactly five properties with extra client keys dropped; re-disputing an already-disputed line is an accepted no-op with no version bump; the plugfest duplicate-participation rule is state-blind (`NO_SHOW` included) while the calendar-overlap rule filters only the participation's state; lock and close carry no clock precondition; `interop_pass_count` enters no calculation anywhere.

### Pass 3 result

542 lines / 148,414 → **542 lines / 154,006 chars** (+5,592). 13 edits. **8 ambiguity-pins, 5 mismatch-revisions.**

Mismatches: §3.8 ¶341 a missing/non-`COMPLETE` plan answers `ERR_MANDATORY_COVERAGE_INCOMPLETE` (rung 43), not `ERR_INVALID_TEST_PLAN_STATE` — which also settles the sub-claim Step 5 had dropped as non-derivable; §3.9 ¶381 revision reporting has **no** ownership check, so any `Member` may report against any listing (PRD had said "the owning `Member`"); §3.10 ¶401 an *absent* `remediation_days` is `ERR_INVALID_REQUEST` at rung 6, with `ERR_INVALID_DATE_RANGE` reserved for out-of-range integers — again settling a Step 5 dropped sub-claim; §3.10 ¶403 `open_case_count` is never recomputed on a case advance, so a `REMEDIATED` case still counts until the member is next recomputed for any reason; §3.3 ¶255 the laboratory-revocation fan-out also recomputes each cancelled event's `distinct_vendor_count` (`cascade.py:251`).

Notable pins: the `fee_escrowed_cents == certification_fee_cents` issuance precondition answers `ERR_INVALID_SUBMISSION_STATE` and is evaluated *before* the attestation checks, and a `dac_serial` stays held after `dac_state` falls to `REVOKED` (`routes/submissions.py:318-332`) — this is the downstream half of the §3.2/§3.8 escrow contradiction Step 8 resolved; readiness tallies and denominators are recomputed by walking `included_feature_set_ids` rather than read from the plan's stored counts, with unresolvable ids dropping out of both; the readiness read renders `score` as a JSON **string** at 2dp while the submission row's two stored scores are plain JSON **numbers** (`85.0` vs `"85.00"`); a submission with no non-`VOIDED` plan is not an error but a `PROVISIONAL` 35.00 with vacuous optional ratio 1.0000. `cascade.release_escrow` confirmed dead code (never called) and therefore given no PRD surface.

### Orchestrator verification

- `wc -l -c`: PRD.md 542/132,424 → PRD_FINALIZED.md 542/133,534 → **PRD_COMPLETED.md 542/154,006** (+16.3% chars over PRD.md, identical line count — every edit was in-paragraph, no new sections, matching the minimal-patch contract).
- `cmp -s PRD_FINALIZED.md PRD_COMPLETED.md` → **differs**. Per the known failure mode where a byte-identical PRD_COMPLETED.md means the scan silently never ran, this confirms all three passes really executed. `diff` reports 94 lines (47 changed line-pairs = 18 + 23 + 13 edits, allowing for paragraphs edited twice).
- Structure intact: §1–§5 headings all present, §5 error table exactly 59 `ERR_` rows, §4 exactly 66 endpoint rows, file ends on a complete table row at a real section boundary — no truncation.
- Drift check: `find workspace/implementation test_suite test_helpers -name "*.py" -newer results.1.json` → **no hits**. Neither the implementation nor the test artifact was touched after the verified green 8-round sweep, so the 8×213/213 result still describes exactly the code on disk.

**Pipeline complete.** All nine steps done; `workspace/PRD_COMPLETED.md` written.
