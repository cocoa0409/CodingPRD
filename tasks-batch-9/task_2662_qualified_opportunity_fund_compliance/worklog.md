# Worklog — task_2662_qualified_opportunity_fund_compliance

## Step 1: Create task directory — 2026-09-04T02:58:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2662_qualified_opportunity_fund_compliance` and `.../workspace`. Index pre-assigned (2662) by the orchestrating prompt; no scan of ./tasks/ performed to avoid collisions with the up-to-32 concurrent pipelines on this host.

## Step 2: Scaffold generation — 2026-09-04T04:44:00.000Z

Wrote the three scaffold artifacts from the scenario text plus the
prd-bench-scaffold-generator specification only (no sibling task was read):

* `SCAFFOLD.yaml` (3349 lines) — §1.0-§1.7: 14 entities, 11 state machines,
  2 §1.2.1 concurrency rules, 11 calculations, 39 prioritized validations,
  62 endpoints, 50 errors, 4 roles. complexity_profile: compliance_audit /
  temporal_windowing, layers [rate_threshold_triggers, cascading_side_effects,
  dual_variant_calculation, optimistic_concurrency], flat topology, cyclic
  state-machine shape, segregation_of_duties role model, immediate consistency.
* `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1796 lines) — §1.8 only: all nine
  difficulty rules, 24 instances (2-3 per rule).
* `SCAFFOLD_CORNER_DESIGN.yaml` (3559 lines) — §1.9 only: nine sections,
  84 instances (62 full test_recipes + 22 excluded_because stubs citing §1.8).

Fix applied during generation: validations priority 13 originally shadowed
priority 14, making ERR_ALREADY_TERMINAL unreachable; P13's check now carries
an explicit terminal-state carve-out and the ERR_INVALID_STATE_TRANSITION
catalog condition matches it.

Audit: all 50 error ids in §1.6 are asserted by a §1.8 or §1.9 instance.
`scaffold_lint.py` verdict: clean lint (62 endpoints, 14 entities,
24 §1.8 instances, 62 §1.9 scanned instances, 645 calls).

## Step 3: Copy shared files — 2026-09-04T04:45:30.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes). All three scaffold artifacts verified present and non-trivial.

## Step 4: PRD generation — 2026-09-04T05:05:00.000Z

Subagent summary (verbatim):

**Output:** `workspace/PRD.md` — **511 lines**, final heading `## 5. Error Codes`, file ends on the last error-table row (`| ERR_CURE_BASIS_NOT_APPROVABLE | 422 |`), not mid-sentence. Written incrementally (one small `Write` + one `cat >>` heredoc append per major section) with `wc -l` after each append; no giant single write, no truncation.

**Section list**
- Title; `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles`: 2.1 RBAC · 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`, diff-verified) · 2.3 Pagination · 2.4 The Logical Clock · 2.5 Common Resource Properties · 2.6 Path Resolution and Referential Integrity · 2.7 Money, Percentages and Rounding Discipline · 2.8 Optimistic Concurrency on Shared Aggregates · 2.9 Conserved Quantities · 2.10 Segregation of Duties · 2.11 Order of Evaluation (numbered 1-39, verified complete and contiguous) · 2.12 Cascade and Recomputation Discipline
- `## 3. Business Logic & Workflows`: 3.1 Taxpayer Onboarding and Intake of Eligible Gain · 3.2 Fund Formation, Self-Certification, Decertification · 3.3 Deferral Elections and the Conserved Gain Ledger · 3.4 The Asset Ledger and the Ninety-Percent Asset Test · 3.5 Operating Businesses and the Three-Prong Zone Test · 3.6 Substantial Improvement Projects · 3.7 The Working Capital Safe Harbor · 3.8 Penalty Assessment, Cure Requests and Cure Decisions · 3.9 Ten-Year Step-Up Elections and the Disposition Sequence · 3.10 Inclusion Events and the Holding-Tier Basis Step · 3.11 The Deadline Sweep
- `## 4. API Endpoints` (1 intro paragraph on 201-vs-200, then a 4-column table, 62 rows)
- `## 5. Error Codes` (2-column table, 50 rows)

**Scaffold coverage (script-verified against SCAFFOLD.yaml, not by eye)**
- **14 entities / 149 field names:** all present verbatim in backticks; including the `common_fields: false` exception (CapitalExpenditure).
- **62 endpoints:** section 4 table rows match scaffold method, path and role list one-for-one (0 mismatches); every endpoint's behaviour/side effects narrated in sections 2-3.
- **50 errors:** all 50 appear in section 2/3 prose *before* section 5, and the section 5 rows match scaffold id+status exactly.
- **39 validations:** the 2.11 ladder enumerates priorities 1-39 with error id, HTTP status and scope, including the priority-13/14 carve-out and the step-up terminal-state exemption.
- **11 calculations:** all narrated with pinned rounding order, constants and worked examples (180-day/292-day deadline variants; 85.0000 FAIL vs 95.0000 PASS valuation variants; 120.0000/90.0000/105.0000 pooled improvement; penalty 50000.00->333.33->1999.98 with 2000.00 named as the wrong order; cure netting 1999.98->1199.99->799.99 with 800.00/1199.98 named as wrong); both conservation invariants in 2.9.
- **11 state machines / 51 unique transitions:** every transition appears with explicit `FROM -> TO` arrow phrasing (verified programmatically), plus both OCC rules (`expected_fund_version`->`ERR_STALE_FUND_VERSION` 412, `expected_project_version`->`ERR_STALE_PROJECT_VERSION` 412).

**Hard contracts:** Contract 1 (field-name coverage) **PASS** — 167 required identifiers, 0 missing (`deferral_election_id` was the only gap found and was fixed). Contract 2 (rule coverage) **PASS**. Contract 3 (section 3 path purity) **PASS**.

One scaffold inconsistency flagged by the generator: the dispose endpoint's `side_effects` say `HELD|IMPROVING -> DISPOSED`, while the FundAsset state machine's declared transition and validation priority 13 both require `HELD`. The PRD follows the authoritative state machine (`HELD` only).

Orchestrator truncation check: `wc -l` = 511, `tail -12` ends on a complete error-table row, and all five top-level sections plus 2.1-2.12 / 3.1-3.11 subsections are present. Not truncated; no regeneration needed.

## Step 6: Implementation generation — 2026-09-04T05:52:00.000Z

Subagent summary (verbatim):

## Files written — `workspace/implementation/`

| file | lines | role |
|---|---|---|
| `start.sh` | 10 | launcher (`exec python3 app.py`, guarded pip install, chmod +x) |
| `requirements.txt` | 1 | `flask>=2.0.0` |
| `app.py` | 60 | Flask app, 4 blueprints, `ApiError`/HTTPException/500 -> PRD error envelope, `app.run(host="0.0.0.0", port=$PORT|10000)` |
| `core.py` | 460 | in-memory `DB` (empty every boot), 51-entry error catalog, envelope/meta, Decimal money helpers, logical clock, `insert`/`touch`/`must_get`/`must_ref`, auth, pagination |
| `schema.py` | 173 | request-body validation (rule 4), unknown-field rejection, spend-schedule coercion |
| `calc.py` | 341 | every declared calculation with pinned rounding orders |
| `derive.py` | 522 | recomputations + all five cascade chains |
| `serialize.py` | 149 | row -> JSON projection (money 2 dp / pct 4 dp as JSON numbers) |
| `support.py` | 77 | listings, scope guards (rules 8-10), state guards (rules 13/14) |
| `routes_core.py` | 317 | clock, deadline sweep, investors, funds (17 endpoints) |
| `routes_gain.py` | 368 | gains, elections, inclusion events, step-ups (12) |
| `routes_asset.py` | 366 | assets, businesses, business tests, asset tests (16) |
| `routes_project.py` | 452 | improvement projects, WCSH plans, penalties (17) |

Total 3296 lines. Storage is in-memory dicts only — no sqlite, no file writes, nothing seeded (verified: a fresh boot reports `total_count 0` on all nine list endpoints).

## Endpoints
**62/62**, and a mechanical diff of the registered Flask URL map against the SCAFFOLD endpoint block matched exactly on both method and path (`ENDPOINTS MATCH SCAFFOLD EXACTLY`).

## Smoke test (port 18662, killed by recorded PID; no pattern kills)
Booted in ~3 s and served five scripted end-to-end flows:
- improvement project: window_end +30 months, basis snapshot, stale `expected_project_version` -> 412, spend -> ratio 120.0000, evaluate -> SATISFIED, asset HELD/QUALIFIED, `adjusted_basis` 1100000.00, second evaluate -> `ERR_ALREADY_TERMINAL`; adjacency (`window_start` = existing last day) -> `ERR_IMPROVEMENT_WINDOW_OVERLAP` (closed geometry)
- aggregated group: pooled ratio 105.0000 promotes the 90%-alone sibling collectively
- WCSH: schedule mismatch 422, aggregate 31% cap 422, spend-on-DRAFT 409, activate -> shelter 60000 / nqfp 0, waterfall `schedule_month_index` = 3, checkpoint 2 survives, checkpoint 6 -> BLOWN -> blown_unspent 35000 / nqfp 35000
- asset test -> penalty: shortfall 450000 -> monthly 3000.00, gross 18000.00 (monthly rounded first); decision on ASSESSED -> `ERR_INVALID_STATE_TRANSITION`; APPROVE of TREATED_AS_FAILURE -> `ERR_CURE_BASIS_NOT_APPROVABLE`; DENY -> UPHELD terminal. Second fund: gross 1800.00 -> credit 1080.00 / net 720.00 (0.60 tier on gross, no second pass), fund posture COMPLIANT, penalty months back to 0
- gains/elections: 180-day arithmetic, `ERR_STALE_FUND_VERSION`, sweep expires the gain, 10-year step-up GRANTED (3654 days) -> STEPPED_UP, partial inclusion from STEPPED_UP -> 409, full inclusion offset 6000.00 (0.15)
- segregation of duties, investor scope, pagination `limit=0` -> 400, unknown path -> 404, all in the `meta`/`response_type`/`data` envelope with `req_`-prefixed ids and 3-digit ISO timestamps

## Ambiguities resolved this session
1. **Improvement project creation on a non-HELD asset.** The FundAsset state machine puts `status == HELD` as a precondition of `HELD -> IMPROVING`, but rule 22 measures the new window against siblings whose status is `OPEN` — reachable only while the asset is already IMPROVING, and rule 13's own enumeration lists "FundAsset HELD for dispose" and nothing about project creation. Resolution: the HELD precondition governs the *side effect* only. A DISPOSED asset is still rejected (`ERR_ALREADY_TERMINAL`), `original_use_in_zone == true` is still `ERR_INVALID_STATE_TRANSITION`, and the IMPROVING->IMPROVEMENT_PENDING stamp fires only from HELD. This keeps all three errors reachable.
2. **`improvement_outcome` when the ratio is >= 100.0000 but the window has closed.** PRD requires a clock strictly before `window_end` for SATISFIED and a ratio strictly below 100.0000 for LAPSED, so neither applies — the project stays OPEN with a refreshed ratio and `evaluated_at`. Corrected `calc.improvement_outcome`, which previously returned LAPSED.
3. **`documentation_complete` reachability.** Bucket-index range/duplicates and a non-blank reference are rule-4 rejections and the planned-sum equality is rule 26, so the only way the flag can be false is `len(spend_schedule) != schedule_month_count`. Therefore "exactly 1..schedule_month_count with no gaps" is NOT enforced at filing time, which is what makes `ERR_WCSH_PLAN_INCOMPLETE` reachable on activate.
4. **Checkpoint index errors:** a non-integer is rule 4; out-of-range or backwards is rule 27 (`ERR_CHECKPOINT_INDEX_INVALID`).
5. **Plan spends never move status** (only the checkpoint does), and plan/project figures are re-touched only when a value actually changed — except the project expenditure, which bumps the project's `version` unconditionally per its explicit side effect.
6. **Scope guards** follow the verbatim `applies_to` lists: no manager scope on business-test create/measure/certify, on project `evaluate`, or on `evaluate-checkpoint`; manager scope does apply to both expenditure POSTs, activate and cure-requests.

Orchestrator note: Steps 5 and 6 were launched in back-to-back messages rather than one; elapsed gap was a few seconds and Step 6 was explicitly forbidden from reading test_helpers/ or test_suite/, so the impl generator's isolation from the test suite held.

## Step 5: Unit test generation — 2026-09-04T06:25:00.000Z

Subagent summary (verbatim):

## Files (task root, not under `workspace/`)

`test_helpers/` — Stage 1: `__init__.py` 105, `api_client.py` 656, `api_errors.py` 141, `assertions.py` 347, `constants.py` 203, `factories.py` 407, `fixtures.py` 1042, `test_users.py` 103, `types.py` 505.

`test_suite/` — 109 tests in 15 files + `conftest.py` 59:

| file | lines | tests |
|---|---|---|
| test_01_investor_and_gain_intake.py | 294 | 6 |
| test_02_fund_lifecycle_and_state_dimensions.py | 357 | 8 |
| test_03_fund_asset_ledger.py | 467 | 8 |
| test_04_asset_test_measurement.py | 552 | 10 |
| test_05_asset_test_period_geometry.py | 165 | 4 |
| test_06_penalty_assessment_and_cure.py | 409 | 10 |
| test_07_deferral_elections.py | 622 | 12 |
| test_08_inclusion_and_step_up.py | 621 | 9 |
| test_09_qozb_business_tests.py | 545 | 8 |
| test_10_improvement_projects.py | 586 | 9 |
| test_11_working_capital_safe_harbor.py | 668 | 11 |
| test_12_decertification_cascades.py | 288 | 3 |
| test_13_authorization_and_scope.py | 423 | 5 (new file) |
| test_14_envelope_and_not_found.py | 180 | 5 |
| test_15_deadline_sweep.py | 146 | 1 (new file) |

## Coverage against the two design indices

- **Queue A (Difficulty, 1.8):** 24 non-stub instances, **all 24 translated**, 48 tests, minimum 2 tests per instance. 0 skipped.
- **Queue B (Corner, 1.9):** 62 non-stub instances, **61 translated** (61 tests), 22 `excluded_because` stubs correctly never translated, **1 skipped**.
- Every test carries exactly one `Design:` line as the final docstring line; no untagged, dual-tagged, stub-pointing or dangling tags (verified by an AST + YAML audit script).

**The one skip:** `Corner/state_machines/wcsh_activate_with_blank_written_plan_reference_rejected` — PRD 3.7 requires "a `written_plan_reference` of 1 to 80 non-blank characters", so a blank reference is a 2.11 rule-4 `ERR_INVALID_REQUEST` (400) at filing; the instance's expected 201-with-`documentation_complete: false` state is unreachable (a bucket-count mismatch is also rule 4, a sum mismatch is `ERR_WCSH_SCHEDULE_MISMATCH`). Left as a gap — no weakened test, no xfail, no placeholder.

## Two deliberate PRD-over-yaml corrections
- `consistency_model/fund_ledger_and_test_results_are_immediately_readable` asserts `gross_penalty_amount == 4000.00`; PRD line 339 pins the rounding order (monthly rounded **first**, then summed) and explicitly rejects multiply-then-round, so the test asserts monthly 666.67 / gross 4000.02 / net 4000.02.
- `endpoints/deadline_sweep_...` asserts the blown plan leaves the business `UNTESTED`; the PRD writes that cascade only as `QUALIFIED -> DISQUALIFIED`/`QUALIFIED -> AT_RISK`, so that one claim was omitted rather than guessed. All other 8 assertions of that instance are asserted.

## Verification passes run
- `pytest --collect-only`: **109 tests collected**, no errors.
- `pyflakes test_suite/*.py`: clean (0 findings).
- Verbatim-quote grep of every docstring quotation against `workspace/PRD.md` (whitespace-normalized): **0 non-verbatim**. Found and fixed 5 pre-existing paraphrases in test_04 (x2), test_07, test_08, test_11.
- Scaffold-citation grep outside the `Design:` tags: 0 hits.
- No `test_helpers/` or `test_suite/` anywhere under `workspace/`; `workspace/implementation/` was never read, nor was any sibling `task_*/`.

Orchestrator verification: `test_helpers/` and `test_suite/` confirmed at the task root; `find workspace -maxdepth 2` returned no stray copies.

## Step 7: Test-and-iterate loop — 2026-09-04T06:52:00.000Z

Subagent summary (verbatim):

**Iterations run:** 2 (each an 8-round parallel `setsid nohup` sweep, per-test-server isolation).

**Iteration 1 result:** 106/109 in all 8 rounds — 3 failures, identical and deterministic across every round (no flakiness, no load-induced failures, no reaping).

**Tests deleted:** none. One assertion pair removed as partial-coverage (STEP 1c):
- `test_08_inclusion_and_step_up.py::test_the_decertification_inclusion_event_applies_the_ten_year_basis_step` — removed the `included_amount == 400000.00` and `included_gain_total == 400000.00` assertions. **COMPUTED-FIELD SILENCE**: PRD 3.10 says only that recording an event "recomputes the election's `included_amount`" and that the figure "grow[s]"; no sentence anywhere gives its formula (verified by grepping every `included_amount` occurrence: 2.7, 3.1, 3.2, 3.3, 3.10). A faithful reader may accumulate `gross_inclusion_amount` (->400000) or `net_inclusion_amount` (->340000); the implementation chose net. This is the only place in the suite where the two readings diverge (everywhere else the tier is `UNDER_FIVE`, so gross == net). The PRD-pinned assertions in the same test (`gross_inclusion_amount` 400000.00, `basis_offset_amount` 60000.00, `net_inclusion_amount` 340000.00, `holding_days` 3653, `holding_tier_applied` TEN_YEAR, `is_full`, `deferred_remaining` 0.00, `deferred_gain_outstanding` 0.00) were all kept.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `make_fund_asset()` gained an optional `headers` parameter. It previously funnelled every kwarg into the payload factory, so a caller registering an asset on a fund owned by a *different* `manager_user_id` (required by PRD 2.11 rule 9, `ERR_FUND_MANAGER_MISMATCH`) leaked `headers` into the JSON body and got `ERR_INVALID_REQUEST - Unknown field 'headers'`. This was the "Setup step failed" behind `test_10::test_the_group_key_is_required_forbidden_and_confined_to_one_fund`.

**Fixes applied to `test_suite/`:**
- `test_02_fund_lifecycle_and_state_dimensions.py::test_the_officer_decertification_couples_the_two_dimensions_in_one_call` — corrected the fund `version` arithmetic from `3`/`4` to `5`/`6`. The test's own comment ("create, self-certify, then the passing cascade") had omitted two PRD-mandated fund mutations: asset registration (3.4 "Registration then recomputes all four fund aggregates" + 2.5 "Recomputation counts as mutation... a fund's four asset aggregates") and measurement (3.4 "sets the fund's `last_test_measurement_date`"). Verified empirically against a live server: create=1, self-certify=2, asset registration=3, measure=4, certify PASS=5, decertify=6.

**Fixes applied to `implementation/`:** none — all three failures traced to the test artifact.

**Final sweep evidence:** results.1 -> 109/109, results.2 -> 109/109, results.3 -> 109/109, results.4 -> 109/109, results.5 -> 109/109, results.6 -> 109/109, results.7 -> 109/109, results.8 -> 109/109 (0 failed, 0 errors in every round).

Orchestrator verification (independent, not taken on trust): all eight `workspace/implementation/results.$i.json` exist (~32.7 KB each, all timestamped 06:49) and each parses to `passed=109 failed=0 errors=0 total=109 skipped=0`.

Step 8 decision: Step 7 was NOT a zero-iteration exit (2 iterations; 1 partial-coverage assertion removal, 1 test_helpers fix, 1 test_suite fix), so Step 8 runs. Note that 0 `implementation/` fixes were applied, so the PRD-silence surface Step 8 must patch is narrow — principally the `included_amount` recomputation formula the STEP 1c removal exposed.

## Step 8: PRD finalization — 2026-09-04T06:57:00.000Z

Subagent summary (verbatim):

## Line counts
- `PRD.md`: 511 lines - `PRD_FINALIZED.md`: 511 lines - **0.0% line delta** (1 of 511 lines revised in place; document still ends on `| ERR_CURE_BASIS_NOT_APPROVABLE | 422 |`).

## Changes
- **3.10 — revise — pinned the formula for a deferral election's `included_amount`: the sum of `net_inclusion_amount` (never `gross_inclusion_amount`) over every inclusion event on that election, client-recorded and system-generated alike, at 2dp — `implementation/derive.py:61` (`included = q2(sum(v["net_inclusion_amount"] ...))`), assigned at `derive.py:80`.**

No other edit was warranted.

## Per-edit pre-edit search log

**Edit 1 (3.10 `included_amount`)**
- (a) **Subject:** the derived money field `included_amount` on a deferral election, and everything that consumes it (`included_gain_total`).
- (b) **Impl paths enumerated:** `grep -rn "included_amount"` over all of `implementation/` returned exactly 6 sites, all read:
  - `derive.py:55-85 recompute_election` — the sole writer; sums `net_inclusion_amount` over **all** `inclusion_events` of the election with no filter on `event_type` or ordering; also writes `included_fraction_total` (capped at 1.0000) and `deferred_remaining` (`elected * (1 - total)`, 0.00 when `REVOKED`).
  - Every caller of `recompute_election`: `routes_gain.py:257` (client-recorded inclusion event), `routes_gain.py:356` (granted step-up), `derive.py:252` (fund-decertification `full_inclusion_cascade`, whose events are minted by the same `calc.inclusion_amounts`, `derive.py:237-249`) — all three reach the identical formula, which is why the wording says "client-recorded and system-generated events alike" (keeps 3.2's cascade consistent).
  - `routes_gain.py:161` — initialized `ZERO2` at election creation; an election with no events sums to 0.00, so the new sentence does not contradict the initial value.
  - `derive.py:99-100 recompute_investor` — `included_gain_total` sums `included_amount` over elections in `INCLUDED_PARTIAL`/`INCLUDED_FULL`; net-based `included_amount` is what makes the removed `included_gain_total == 400000.00` assertion wrong (impl yields 340000.00).
  - `serialize.py:40` — plain money serialization, no transformation.
  - Also checked `routes_gain.py:204-207` (revoke) — sets `deferred_remaining` to 0.00 directly and cannot coexist with inclusion events, so it never contradicts the sentence.
- (c) **Wording adjustment:** added "client-recorded and system-generated events alike" so the sentence stays true of the 3.2 decertification cascade path that Step 7 exercised only at the certification-driven site; deliberately left `included_fraction_total` and `deferred_remaining` wording untouched (their partial-inclusion formulas are a separate, un-flagged silence — widening there would be out of scope and risks a new mismatch).

## Step 7 items deliberately **not** patched
- **`test_helpers/fixtures.py::make_fund_asset(headers=...)`** — pure fixture bug. Enumerated `core.py:419-435` (auth), `schema.py`/`support.py` `parse_body` (unknown field -> `ERR_INVALID_REQUEST`) and `routes_asset.py` asset-record ownership check; the impl order matches PRD 2.11 rules 4 -> 9 verbatim. Nothing under-determined.
- **`test_02` fund `version` arithmetic 3/4 -> 5/6** — PRD already determines all six increments (create, self-certify, aggregate recomputation on registration, measurement, certify PASS, decertify). Also checked `core.py:321-334`: `touch()` is idempotent per HTTP request, so a multi-field fund mutation still bumps by exactly 1 — which is what 2.5/3.2/3.4's "by 1" phrasing already says. No PRD silence, so no edit.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` is a genuine non-empty single-hunk change at line 369 (4 diff lines total); both files are 511 lines; PRD_FINALIZED.md still ends on the last error-table row. Not a byte-identical copy.

## Step 9: PRD completeness scan — 2026-09-04T07:20:00.000Z

Run as three sequential file-partitioned passes over one shared `PRD_COMPLETED.md`, so no single pass could exhaust its budget and silently emit a byte-identical copy. Pass A created the file from `PRD_FINALIZED.md`; Passes B and C edited it in place (Edit only, never Write).

### Pass A — app.py / core.py / schema.py / serialize.py / support.py
511 -> 517 lines, 109,092 -> 115,457 chars. 11 ambiguity-pins, 1 mismatch-revision.
- 2.2 — revise — `api_request_id` is `req_` + exactly 20 chars from A-Z0-9; `api_request_timestamp` from the host clock at response time, not the logical clock — core.py:369-383
- 2.2 — revise — every declared field always present; "empty" means JSON `null`, not omitted; only `updated_at`/`version` on capital expenditures are ever absent — serialize.py:123-145
- 2.2 — revise — single-resource `meta` carries only `api_request_id`/`api_request_timestamp` — core.py:376-388
- 2.3 — revise — exact `has_more` definition; out-of-range `offset` yields an empty `data` array, not an error; `limit`/`offset` echo effective values — core.py:391-403
- 2.3 — revise — filters are case-sensitive exact string equality; an empty field never matches; undeclared query params ignored — support.py:13-29
- 2.4 — revise — **mismatch** — the blanket "nothing reads the host wall clock" now carves out `api_request_timestamp`, `created_at`, `updated_at`, which are host-clock stamps forced strictly increasing at ms resolution — core.py:179-193
- 2.4 — revise — client-instant parsing accepts `Z`, explicit `+HH:MM`, zone-less read as UTC, bare `YYYY-MM-DD`; anything else `ERR_INVALID_REQUEST` — core.py:196-213
- 2.5 — revise — the unit of mutation is the *request*: repeated direct+cascade touches move `version` by exactly 1; a row created in a request stays at `version` 1 — core.py:300-334
- 2.6 — insert — trailing slash insignificant; unrouted path -> `ERR_INVALID_REQUEST` 404; undeclared method -> 405; both in the standard envelope — app.py:22,33-40
- 2.7 — insert — money as string/boolean/non-finite is `ERR_INVALID_REQUEST`; >2dp quantized half-up *before* bounds checks (0.004 -> 0.00 fails "> 0.00"; 0.005 -> 0.01 passes) — schema.py:104-115
- 2.7 — revise — percentages are JSON numbers, never strings; scale fixed per field by section 3 — serialize.py:123-133
- 2.11 rule 4 — revise — absent/whitespace-only/literal `null` body reads as `{}`; invalid JSON or non-object is 400; body parsed regardless of `Content-Type` — schema.py:38-50, app.py:41-43
- 5 preamble — insert — `ERR_INVALID_REQUEST` is the one id reused outside the ladder, at 404/405 and 500 — app.py:33-51

### Pass B — calc.py / derive.py
517 -> 517 lines, 115,457 -> 120,566 chars (all in-paragraph). 10 ambiguity-pins, 4 mismatch-revisions.
- 2.4 — insert — month arithmetic: whole calendar months, day-of-month clamped **down** to the target month's last day (2026-07-31 + 31 months -> 2029-02-28); covers both the 30-month and 31-month windows — core.py:221 via calc.py:161,210
- 3.4 — insert — degenerate asset test is not a vacuous pass: empty/zero included set -> ratio 0.0000, `FAIL`, shortfall 0.00 — calc.py:85-99
- 3.4 — revise — **mismatch** — decertification triggers on `consecutive_failed_tests` >= 2 alone; the "already `DEFICIENT`" precondition removed — derive.py:304
- 3.4 — revise — **mismatch** — `consecutive_failed_tests` is an incrementally maintained counter (reset by `CERTIFIED_PASS` and by an approved cure), not a re-derived run length — derive.py:283,278,455
- 3.5 — insert — `wcsh_protected_amount`: each `covered_amount - spent_total` term rounded to 2dp before the sum and **not** floored at 0.00; `DRAFT`/`COMPLETED` plans enter neither sum — derive.py:208-211
- 3.5 — insert — with no `MEASURED` asset test, disqualification-cascade links 3 and 4 are absent; the `DEFICIENT` move is unconditional on prior posture and does not fire when the re-measured test reads `PASS` — derive.py:341-346
- 3.5 — revise — **mismatch** — `consecutive_failed_business_tests` is a carried counter, also raised by the 3.7 plan-blowout cascade with no failed test at all — derive.py:372-379,416
- 3.6 — insert — a group-satisfied sibling does not get `evaluated_at` stamped — derive.py:495-509
- 3.6 — insert — asset promotion rewrites `qualification` unconditionally but moves `status` only from `IMPROVING` — derive.py:480
- 3.6 — insert — the two outcome branches are independent, not fallbacks: ratio >= 100.0000 AND clock >= `window_end` matches neither and stays `OPEN` — calc.py:196-202
- 3.7 — insert — a spend no bucket could absorb records `schedule_month_index` empty — calc.py:230-243
- 3.7 — insert — "latest `MEASURED` business test" = greatest `testing_date`, ties on later creation; only the three nqfp fields re-derived; disqualifying branch fires from any status except `DISQUALIFIED` — derive.py:388-416
- 3.8 — insert — cure request moves the posture only out of `DEFICIENT` — derive.py:439-441
- 3.8 — insert — cure approval floors `cumulative_penalty_months` at 0; the `COMPLIANT` write is unconditional — derive.py:452-455
- 3.11 — revise — **mismatch** — expiry freezes only the gain's `status`, not `unelected_amount` — derive.py:35-44

### Pass C — routes_core.py / routes_gain.py / routes_asset.py / routes_project.py
517 -> 517 lines, 120,566 -> 128,774 chars, 25 Edit calls. 14 ambiguity-pins, 11 mismatch-revisions.
- 2.11 rule 4 — revise — mismatch — spend-schedule buckets need only integer `month_index` in 1..31 with no duplicates; index/count agreement feeds `documentation_complete` instead — schema.py:160-171, routes_project.py:233-235
- 2.11 rule 12 — insert — mismatch — on election create and asset record the decertification lockout precedes the certification gate — routes_gain.py:127-130, routes_asset.py:52-55
- 2.11 rule 14 — revise — mismatch — dropped `DECERTIFIED` fund and `EXPIRED` gain from the terminal list — support.py:62-70
- 4 `GET /qof/fund-assets` — revise — mismatch — removed the non-existent `asset_class` filter — routes_asset.py:103-106
- 3.2 — insert — `reason_note` <= 500 chars, validated then discarded — routes_core.py:258
- 3.3 — insert — the inclusion-event bar on revoke is `ERR_INVALID_STATE_TRANSITION`, after the `DEFERRED` guard — routes_gain.py:200-203
- 3.3 — insert — (B6) `holding_tier` re-resolved on exactly three requests; clock advance / revoke / read never refresh it — routes_gain.py:257,356, derive.py:252
- 3.4 — insert — an `IMPROVING` asset is not disposable — routes_asset.py:117
- 3.4 — insert — (B1) `measurement_date` unconstrained against the period and `failed_month_count` unfloored, so a negative count propagates into a negative gross/net penalty — routes_core.py:280-288, calc.py:97-99
- 3.4 — revise — mismatch — `last_test_measurement_date` is an unconditional last-write stamp and can move backwards — routes_asset.py:343
- 3.5 — revise — mismatch — business-test creation is outside the rule-9 ownership fence and does not consult `certification_status` — routes_asset.py:207-211
- 3.5 — insert — (B2) the tangible component is not floored at 0.0000; `nqfp_pct` carries no cap — routes_asset.py:267, calc.py:139-143
- 3.6 — insert — the `original_use_in_zone` bar is `ERR_INVALID_STATE_TRANSITION`; an already-`IMPROVING` asset may take another project; both side-effect writes apply only from `HELD` — routes_project.py:58-64,103-104
- 3.6 — revise — mismatch — evaluate is not manager-fenced — routes_project.py:180
- 3.6 — revise — mismatch — (B4) the `IMPROVING` check is a precondition of the satisfy branch, so a ratio-complete in-window project whose asset left `IMPROVING` matches neither branch — routes_project.py:190-194
- 3.7 — revise — mismatch — gapped spend schedules are accepted and can even be fully documented — schema.py:160-171, routes_project.py:261-262
- 3.7 — insert — (B3) plan-expenditure logging leaves `pacing_shortfall` and `last_checkpoint_month_index` stale; an excluded `LAND_ACQUISITION` spend moves no plan figure and no `version` — calc.py:247-254, routes_project.py:206-216,349
- 3.7 — revise — mismatch — the checkpoint is not manager-fenced — routes_project.py:368
- 3.7 — insert — a no-op checkpoint moves neither `version` nor `updated_at` — routes_project.py:206-216
- 3.8 — insert — `narrative_reference` is 1 to 200 non-blank characters — routes_project.py:421-422
- 3.9 — insert — only the `STEPPED_UP` status write is conditioned on `DEFERRED`; basis/pct/tier rewritten unconditionally on a grant — routes_gain.py:340-346
- 3.10 — insert — a sub-1.0000 fraction against a `STEPPED_UP` election is `ERR_INVALID_STATE_TRANSITION`, after the state guard and before the ceiling — routes_gain.py:235-237
- 3.11 — revise — mismatch — expired-gain dollars are barred by the 180-day gate, not by any terminal check; the two rules differ by one day — routes_gain.py:115-171
- 3.11 — insert — the sweep tests the stored `improvement_ratio_pct` without re-running the ratio — routes_core.py:66-71, derive.py:513-522

### Pass C hand-off verdicts
- **A1 — no change (unreachable).** No route resolves `capital_expenditures`, `inclusion_events` or `step_up_elections` by id and none has a single-resource GET, so those three 404 ids are unreachable. Section 5 and 2.6 left alone.
- **A2 — verified, 2 deviations pinned.** All 14 `guard_state` tuples match the declared machines; fund `DECERTIFIED` surfaces as `ERR_FUND_DECERTIFIED`, gain `EXPIRED` is never guarded. Both written into rule 14.
- **A3 — 1 divergence pinned.** Rule 12 precedes rule 11 on election create and asset record; all other precedences conform.
- **A4 — 2.3 exact; section 4 wrong.** All 18 filter tuple sets match 2.3 verbatim; the spurious `asset_class` filter claim removed.
- **B1 — not validated; pinned** in 3.4. **B2 — not enforced; pinned** in 3.5. **B3 — confirmed; pinned** in 3.7. **B4 — route matches, but a second-order mismatch was revised** (3.6's "unconditional `qualification` rewrite" held only for the lapse branch and group siblings). **B5 — confirmed unreachable; no change.** **B6 — pinned** in 3.3.

### Orchestrator verification
- `wc -l`: PRD.md 511, PRD_FINALIZED.md 511, PRD_COMPLETED.md 517. `wc -c`: 109,092 -> 128,774 (+19,682 chars). `diff PRD_FINALIZED.md PRD_COMPLETED.md` shows 86 changed lines — the scan genuinely ran; PRD_COMPLETED.md is NOT a byte-identical copy.
- `tail -2 PRD_COMPLETED.md` ends on the last error-table row; not truncated.
- `find . -name worklog.md` returns only the task-root copy — no stray append drifted into `workspace/`.
- Every `.py`/`.sh` file under `implementation/`, `test_suite/` and `test_helpers/` has an mtime at or before 06:46, i.e. all predate the 06:49 green sweep. Steps 8 and 9 were documentation-only and did not disturb the passing state.

**PIPELINE COMPLETE.** All 9 steps done; `workspace/PRD_COMPLETED.md` written.
