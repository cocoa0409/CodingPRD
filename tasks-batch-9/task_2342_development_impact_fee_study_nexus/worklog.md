# Worklog — task_2342_development_impact_fee_study_nexus

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2342_development_impact_fee_study_nexus/` and `tasks/task_2342_development_impact_fee_study_nexus/workspace/` (pre-allocated name used verbatim; no index scan).

## Step 2: Generate scaffold — 2026-09-01T23:03:00.000Z

Scaffold generation for task 2342 is complete and passes the linter.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2342_development_impact_fee_study_nexus/`)
- `SCAFFOLD.yaml` (3081 lines) — §1.0–§1.7 only; verified to contain neither `scaffold_difficulty_design` nor `scaffold_corner_design`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2981 lines) — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (5211 lines) — single key `scaffold_corner_design`

**Scaffold content (§1.0–§1.7)**
- `difficulty_level: expert_plus`; archetypes compliance_audit / ledger_reconciliation; topology flat; state-machine shape cyclic; role model segregation_of_duties; consistency immediate; layers: dual_variant_calculation, cascading_side_effects, derived_field_reconciliation, optimistic_concurrency
- 10 entities (FeeProgram, FacilityCategory, FeeStudy, NexusComponent, FeeScheduleItem, ProtestFiling, DevelopmentApplication, CreditClaim, DeferralAgreement, FundLedgerEntry)
- 7 state machines, 3 concurrency rules (program/application/category OCC), 9 calculations, 54 validations (priority 1–54), 43 endpoints, 54 errors, 6 roles, 2 segregation-of-duties rules

**§1.8 Difficulty design** — 25 instances across all 9 rule_ids (dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 3, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 3).

**§1.9 Corner design** — 73 instances over 9 sections: entities 12, state_machines 15, calculations 12, validations 8, endpoints 6, errors 8, rbac 5, cross_cutting_complexity_layers 6, consistency_model 1. 53 carry full `test_recipe`s; 20 are `excluded_because` stubs, each citing an existing §1.8 instance by name.

**Verification performed**
- `scaffold_lint.py` → `VERDICT: clean lint` (43 endpoints, 10 entities, 25 + 53 instances, 1499 calls scanned)
- All 54 declared `error_id`s are triggered somewhere in the two design files (0 uncovered); the last six closed in this pass were ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, ERR_NOT_APPLICATION_OWNER, ERR_SEGREGATION_OF_DUTIES, ERR_REPORT_PREPARER_CONFLICT, ERR_STALE_CATEGORY_VERSION
- Instance names unique across both files; no unbound `${var}` in any recipe; every stub citation resolves
- Audited every `expected_<entity>_version` against the endpoint output that produced its capture and fixed two semantically wrong captures: `prog_v2` was read off a `POST /fee-studies` response (now a `GET /fee-programs/${prog_id}`), and `app_v2` in `administrative_charge_rounds_per_line_then_sums` was read off a `POST /credit-claims/{id}/decide` response, whose `output` is `CreditClaim`, not the application (now a `GET /development-applications/${app_id}`)
- Setup-chain ordering replay flagged only 4 deliberate negative orderings (assess before activation, adopt before window close, plus the two role-denial calls that must 403 ahead of the state/balance checks)
- Relabelled the paging instance from `claim_type: pagination_with_filtering` in `cross_cutting_complexity_layers` to `claim_type: listing` under `entities`, since that layer is not declared active in `complexity_profile.complexity_layers`
- Cross-checked every field, enum value and query parameter asserted by the new rbac/cross-cutting/consistency recipes against §1.1/§1.5 (e.g. `last_report_status` NOT_FILED|FILED_ON_TIME|FILED_LATE, `fund_posture`, the inline annual-report output shape, the `assessment_status`/`collection_status` filters)

## Step 3: Copy shared files — 2026-09-01T23:06:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2342_development_impact_fee_study_nexus/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T23:26:00.000Z

PRD written to `workspace/PRD.md` — **446 lines**, ending at §5 with no audit footer.

**Structure**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications & System-Wide Principles — 11 domain-derived subsections: 2.1 User and Role-Based Access Control, 2.2 API Response Structure (pasted verbatim, byte-identical to `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Record Identity, Audit Stamps and the Logical Clock, 2.5 Money, Basis Points and Rounding Discipline, 2.6 The Statutory Constants of a Fee Program, 2.7 Reading Nested and Reverse-Reachable Collections, 2.8 Optimistic Concurrency on Parent Records, 2.9 Segregation of Duties, 2.10 Validation Precedence and Error Selection, 2.11 Derived Field Reconciliation and Cascade Discipline
- §3 Business Logic & Workflows — 9 subsections: program/facility standards, study drafting and the dual cost allocation, fee schedule conversion, certification->notice->protest->adoption->effect, revision and the four-hop decertification cascade, application pricing (7-step assessment), credit claims and the overpayment they create, collection/deferral/default/certificate, the fee fund (FIFO vintages, posture, statutory refunds, annual reporting)
- §4 Endpoint Definitions — 4-column table, all 43 endpoints
- §5 Error Code Catalogue — 2-column table, all 54 error IDs

**Coverage audit (all three Hard Contracts PASS)**

```
Field coverage check:
- entities[].fields: 140 required, 140 present, 0 missing
- endpoints[].request_body: 86 required, 86 present, 0 missing
- endpoints[].query_params: 41 required, 41 present, 0 missing
- endpoints[].path_params: 1 required, 1 present, 0 missing
Status: PASS
```
(Two independent verification passes run; first pass found `nexus_component_id` missing, which was added to §3.3. Endpoint `output` identifiers were audited separately — all present.)

```
Rule coverage check:
- validations[] with priority: 54 checked, 54 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 43 checked, 43 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed, 0 missing
- validations[] conditions: 54 checked, 54 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 78 side_effects + 12 multi-endpoint applies_to sets checked, all expressed, 0 missing
- entities[].fields[] structured content: 140 checked (incl. assessed_lines' 7 object keys, all enum value sets, all defaults/ranges, all derived-field formulas), 140 reconstructible from prose, 0 missing
- sibling-branch symmetry: 14 groups checked, 14 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 911
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Notes on judgement calls**
- Automated scan confirms zero pseudocode leakage (`==`, `>=`, `+=`, `min()`, `max()`, `round()`, `IN {}`, `AND`) and zero fuzzy-quantity words outside the verbatim §2.2 block.
- First draft nominated `ERR_COMPONENT_ALLOCATION_STALE` for adopting a schedule line on a non-`VALID` component; the scaffold scopes that error to only certify-nexus and assess, so the invented scope was removed and the requirement is stated without an error ID (matching the scaffold's own field note).
- The scaffold has one internal spelling discrepancy — `FeeProgram.last_report_status` defaults to `NOT_FILED` while the create side-effect and the annual-report read say `UNFILED`. Both are surfaced: the persisted field is `NOT_FILED`, the report read's `report_status` is `UNFILED`.
- The two deliberately inverted priority orderings (30 above 53, 41 above 42) and the closed-inclusive year interval vs half-open timestamp interval contrast are called out explicitly with worked boundary cases.
- Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-02T01:24:00.000Z

The suite is complete. Final state and audit results:

## Files written

**`test_helpers/`** (Stage 1, complete and unchanged since generation): `__init__.py`, `api_client.py`, `api_errors.py` (54 error ids + HTTP map), `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`.

**`test_suite/`**: `conftest.py` plus 18 test modules, **102 tests collected**.

| queue | files | tests |
|---|---|---|
| A (difficulty, §1.8) | `test_01_cost_allocation_variants.py` (4), `test_02_nexus_formula_and_admin_charge.py` (6), `test_03_study_and_collection_state_machines.py` (6), `test_04_cascades.py` (6), `test_05_validation_priority.py` (6), `test_06_boundaries.py` (6), `test_07_cross_entity_state.py` (5), `test_08_temporal_overlap.py` (4), `test_09_invariants.py` (6) | **49** |
| B (corner, §1.9) | `test_10_entities.py` (12), `test_11_state_machines.py` (7), `test_12_calculations.py` (7), `test_13_validations.py` (6), `test_14_endpoints.py` (4), `test_15_errors.py` (8), `test_16_rbac.py` (5), `test_17_concurrency.py` (3), `test_18_consistency.py` (1) | **53** |

## Design-index coverage (verified programmatically)

- **78/78 non-stub instances covered**, zero uncovered: 25 difficulty instances (9 rule ids) -> 49 tests; 53 corner instances (9 sections) -> 53 tests, exactly one test per corner instance.
- Every test carries exactly one `Design:` line; no unknown tags, no dual tags, no test tagged to one of the 20 `excluded_because:` corner stubs (which are cross-references to difficulty instances, not gaps).

## Audit passes run

- **PRD-citation sweep**: greedy maximal-verbatim-run analysis of every docstring against `workspace/PRD.md`. Fixed 16 real defects — one invented sentence in `test_01` and fifteen quotes truncated at a PRD colon/semicolon (`test_01`x4, `test_02`x4, `test_04`x4, `test_05`x2, `test_07`, `test_13`, `test_15`) — plus two missing backtick pairs. Now every docstring is fully verbatim except four benign sentence-seam runs (each a complete short PRD sentence such as "The study's `version` increments."), and every citation has a distinctive >=8-word literally-greppable substring.
- **Scaffold-citation sweep**: no occurrence of "scaffold", §1.x, "queue A/B" or table references anywhere in generated code.
- **Hygiene**: `py_compile` clean; `pyflakes` clean over both directories (removed three unused imports); `pytest --collect-only` collects all 102.

## Design-vs-PRD conflicts resolved in favour of the PRD (asserted PRD behaviour, no weakening)

1. Program `last_report_status` starts `NOT_FILED`; the report read's own `report_status` uses `UNFILED` (PRD §2.6 states both spellings).
2. Deferral `due_at` is null at birth (§3.8), not the echoed `requested_due_at` the corner design asserts.
3. Corner design's `{success: true, error_id: null}` envelope prose replaced throughout by the real envelope via `validate_success`/`validate_error`.
4. Queue A instance 19 (`certificate_of_occupancy_is_blocked_by_an_open_deferral_agreement`) emitted as one test, not two: the design's second branch has a DENY succeed after the fee is `PAID`, but §3.8 requires `collection_status` `DUE` for either deferral decision.
5. Queue A instance 8 (`deferral_default_then_payment_joins_back_to_satisfied`) asserts only PRD-derivable values; the design's `paid_cents == 5708473` contradicts §2.11's COLLECTION - REFUND derivation.

## Instances skipped

None. No instance failed the PRD-first two-condition filter, so no gaps were left and no placeholders, skips or xfails were emitted.

**Orchestrator note:** Steps 5 and 6 were specified to launch concurrently in one message; they were in fact launched sequentially (Step 5, then Step 6). The physical-isolation benefit was therefore replaced by an explicit hard prohibition in the Step 6 prompt against reading `test_helpers/` and `test_suite/`.

## Step 6: Generate implementation — 2026-09-02T02:00:00.000Z

Implementation complete and verified.

## Files written

`workspace/implementation/` — 21 Python modules (3,148 lines), plus `requirements.txt` (`flask>=3.0`) and `start.sh`.

**Layout**
- Entry: `app.py` (blueprint registration, `ApiError`/HTTPException/catch-all handlers that always emit the envelope, global `RLock` per request), `start.sh` (guarded `pip install`, `exec python3 app.py`, binds `0.0.0.0:$PORT` default 10000).
- Infrastructure: `errors.py` (54-code catalog), `util.py` (Decimal/ROUND_HALF_UP helpers, `Body` schema validator, `forbid_versions`), `clock.py` (logical clock, default `2026-08-01T00:00:00Z`), `db.py` (10 in-memory dicts + `annual_reports`, `new_record`/`touch`/`ordered`), `response.py` (envelope + pagination), `middleware.py` (auth/roles), `serializers.py`, `helpers.py` (enums, id resolvers, query filters).
- Services: `derive.py` (graph traversals + full recomputation of every derived field), `calc.py` (growth units, plan/standard cost, nexus ratio, credit valuation), `assess.py` (7-step pricing), `cascade.py` (4-hop decertification, 3-hop activation), `ledger.py` (collection, FIFO expenditure, refunds, deadline sweep), `report.py` (half-open fiscal windows, filing).
- Routes: `programs.py` (9), `studies.py` (17), `applications.py` (12), `fund.py` (3), `clock_routes.py` (1) = **43 endpoints**, matching the PRD exactly.

## Verification

Wrote three throwaway smoke suites (in `/tmp`, not in the repo) and ran each against a freshly booted `start.sh`; all pass. They reproduce every pinned number in the PRD: `1962.0000` growth units; `116667`/`135000`/`101667`/`1.1667` and `247197`/`1.0194` allocations; `254168`/`183001`/`249669`/`1606781` per-unit fees; gross `5,038,370` with per-line admin `151,151` -> net `5,189,521`; present values `973,307` and `888,996`; collection row `2,617,930`; overpayment refund `1,030,000` leaving `1,587,930` OPEN; FIFO partial consumption; the `COMPLIANT -> AT_RISK -> REFUND_DUE` boundary at 2030-05-10/2031-05-10; half-open fiscal window with `FILED_LATE`; notice-window adjacency accepted vs. strict-interior rejected; closed-year horizon overlap; the decertification and activation cascades. Also confirmed all 54 error ids and HTTP statuses match the PRD §5 table programmatically, and that a fresh process has zero entities in every table with the clock at its default.

## PRD ambiguities resolved

1. Creating a fee-schedule item on a non-`VALID` component -> `ERR_COMPONENT_ALLOCATION_STALE`, checked after `ERR_STUDY_INVALID_STATE`.
2. `assess` requires only `allocation_status == VALID` on the effective study's components (unlike `certify`, which also requires >=1 line).
3. System reassessment on credit approval reuses `pinned_fee_study_id`, stamps `reassessed_at`, leaves `reassessment_required` alone, and does not require an effective study.
4. `credit_applied_cents = min(total raw approved, cap)` per §3.6 steps 4/7, even when per-line clamps leave a surplus unassigned (PRD wins over the scaffold's "sum of line credits").
5. `POST /development-applications` with an unresolvable `fee_program_id` -> `ERR_INVALID_REFERENCE` (404), though the validations table lists that code only for three other creates.
6. Credit-claim category resolution uses the program's currently `EFFECTIVE` study; no effective study -> `ERR_CREDIT_CATEGORY_NOT_IN_STUDY`.
7. `created_at`/`updated_at` come from the logical clock (required by report windowing on EXPENDITURE `created_at` and the FIFO tie-break); `api_request_timestamp` uses wall time.
8. `planned_growth_share_bp` treated as optional (default 10000) per §3.2, despite the scaffold endpoint listing it as required.
9. Payment `amount_cents` accepts any integer so `ERR_PAYMENT_AMOUNT_MISMATCH` can surface; expenditure `amount_cents` must be >=1.
10. Annual-report `filed_late` is prospective while unfiled and stored once filed; the read's `report_status` is `UNFILED`/`FILED_ON_TIME`/`FILED_LATE` while the program field uses `NOT_FILED`.
11. REFUND rows carry `development_application_id` copied from the source COLLECTION row so `paid_cents` recomputes on both refund variants.
12. Query enum filters are validated against their declared sets (-> `ERR_INVALID_REQUEST`); unknown query params and unknown body fields are ignored, except the three `expected_*_version` fields, which are rejected on any endpoint that does not declare them.
13. `POST /_clock/set_current_utc` skips authentication entirely but still rejects a present-but-unknown `X-User-Role` with `ERR_UNAUTHORIZED`.

## Step 7: Run tests and iterate — 2026-09-02T03:20:00.000Z

Green: 8/8 rounds, 102/102 passed, `failed 0` / `errors 0` in every round.

## Iterations run
**3** full 8-round parallel stability sweeps (`--isolation per-test-server`, no early exit).

| Iteration | Result |
|---|---|
| 1 | 12 tests failing in **all 8** rounds (3 clusters, deterministic — not flakiness) |
| 2 | `failed 0` in all 8 rounds; 157 residual `error` entries, programmatically confirmed 100% harness-level (`subprocess.TimeoutExpired: lsof -ti:PORT -sTCP:LISTEN ... timed out after 5 seconds`) |
| 3 | **`total 102, passed 102, failed 0, errors 0, skipped 0` in all 8 rounds** |

Iteration 2's residual errors were host contention, not the artifact: ~364 concurrent benchmark pipelines / 3668 processes made real `lsof` take ~4.08s against the runner's hard-coded, non-configurable 5s port-cleanup budget in `prd-bench-local-runner/src/prd_bench_local_runner/pytest_plugin.py::_kill_port`. I did **not** modify shared runner infrastructure; I put a correctness-verified `ss`-based `lsof` shim (~0.86s) on `PATH` for my sweep only. That shim and my sweep/quick driver scripts were harness plumbing and have been deleted — the task directory now contains only the artifact.

## Tests deleted
**None.** Every failure in iteration 1 survived STEP 1a (verbatim PRD coverage) and STEP 1b (unique derivability), so all three clusters resolved at STEP 2 or STEP 3. No assertion was weakened, no `error_id` check was downgraded to an HTTP-status check, and no `skip`/`xfail` was added.

## Fixes applied to `test_helpers/`
- `test_helpers/assertions.py` — `assert_category_fund` (assertion helper): compared `oldest_unexpended_vintage_at` by raw string equality (`expected 2026-05-10T00:00:00Z, got 2026-05-10T00:00:00.000Z`), failing 6 tests. PRD §2.11 pins *which instant* the field holds ("the earliest `vintage_at` among its `COLLECTION` rows whose `entry_status` is `OPEN`, `PARTIALLY_EXPENDED` or `REFUND_DUE`") but pins no fractional-second rendering for clock-written timestamps, so the assertion now uses the module's existing `assert_timestamp_equals` instant normalizer. Strictly more faithful — still asserts the exact instant, just not an underivable rendering.

## Fixes applied to `test_suite/`
- `test_suite/test_13_validations.py` — `test_the_annual_report_may_be_filed_the_instant_the_year_closes`
- `test_suite/test_16_rbac.py` — `test_the_officer_who_authorized_a_years_spending_may_not_report_it`

  Both asserted `200` on annual-report filing. PRD §4 verbatim lists "an annual report filing" among the operations that "bring a new record into existence return `201 Created`", so the expectation was a mis-translation; changed to `validate_success(..., 201)`.

## Fixes applied to `implementation/`
- `workspace/implementation/routes/applications.py` — `create_credit_claim` (`POST /development-applications/<id>/credit-claims`): both amount fields carried an unconditional `minimum=1`, so 5 tests died in setup with `HTTP 422 ERR_INVALID_REQUEST` when a `DEVELOPER_IMPROVEMENT` claim passed `annual_tax_contribution_cents=0`. PRD §3.7 scopes "must be strictly positive" to whichever field the declared `credit_type` makes *required*, and separately states "an amount field that is absent counts as zero" — so 0 == absent on the non-required field and the blanket check was not PRD-required. Strict positivity is now conditioned on `credit_type`. Verified `test_05_validation_priority.py`'s `MALFORMED_CLAIM` (`improvement_value_cents: -5` with `DEVELOPER_IMPROVEMENT`) is still rejected.

## Invariants held
No entity data seeded, preloaded or hardcoded at startup (`db.py`: "In-memory storage. Nothing is ever seeded: every table starts empty."); grep confirms no SQLite, no `open(`, no `json.dump`, no `/tmp` cache, no external persistence anywhere in `implementation/`. No endpoint, response field, side effect, header or capability was added. No PRD-required implementation check was removed to accommodate a fixture. `SCAFFOLD*.yaml` were never consulted for behavioral authority and no sibling task directory was read.

**Orchestrator note:** the Step 7 subagent deleted its `results.*.json` alongside its plumbing scripts, so the orchestrator re-ran the 8-round sweep itself to regenerate `workspace/implementation/results.{1..8}.json` as the artifact's final evidence (same `ss`-based `lsof` shim on PATH only for the sweep, since real `lsof` still takes ~3.8s against the runner's 5s budget on this host).

## Step 8: Finalize PRD — 2026-09-02T03:50:00.000Z

Done. `PRD_FINALIZED.md` created with two inline pins.

**Line counts:** PRD.md 446 lines -> PRD_FINALIZED.md 446 lines (0.0% line delta; both edits are inline inside existing paragraphs). Word count 12,866 -> 13,013 (+147 words, +1.14%).

**Changes**

- §2.4 (Record Identity, Audit Stamps and the Logical Clock) — insert — pinned that *every* timestamp the service returns is rendered as ISO 8601 UTC with exactly three fractional digits (so a clock at `2026-05-10T00:00:00Z` renders `2026-05-10T00:00:00.000Z`), covering clock-written fields, stored client-supplied instants, the annual report's computed window/deadline fields and the clock echo; sub-millisecond precision is truncated in the rendering only, comparisons use the instant — `implementation/util.py:80` (`iso_ms`), reached from `implementation/serializers.py:183`, `implementation/services/report.py:89,109,110,116,144`, `implementation/routes/clock_routes.py:21`, `implementation/response.py:22`.
- §3.7 (Credit Claims) — insert — pinned that strict positivity attaches only to the amount field the declared `credit_type` makes required; the other amount field is optional and may be omitted **or supplied as 0** (contributing nothing), while a negative value in either field is `ERR_INVALID_REQUEST` — `implementation/routes/applications.py:213-222`.

No PRD edit for the third Step 7 item (annual-report filing `201`): §4 already states verbatim that an annual report filing returns `201 Created`, and `implementation/routes/programs.py:119` returns `201`. That was a pure test mis-translation.

**Per-edit pre-edit search log**

Edit 1 — §2.4 timestamp rendering
- (a) Subject: the wire rendering of every timestamp-valued field, triggered by `assert_category_fund`'s `oldest_unexpended_vintage_at` string mismatch (`...00Z` vs `...00.000Z`).
- (b) Paths enumerated: `grep -rn "isoformat|strftime|iso_ms" implementation/` -> the *only* timestamp formatter is `util.iso_ms` (three-digit `%03d` from `microsecond // 1000`). Consumers read in full: `serializers.convert` (applies to every `datetime` on all ten entity serializers, including `requested_due_at`/`due_at`, `vintage_at`/`deadline_at`, `filed_at`, `co_issued_at`, and nested `assessed_lines`); `services/report.py` `compute` (`window_start`, `window_end`, program- and per-category `earliest_deadline_at`) and `file_report` (`filed_at`); `routes/clock_routes.py` echo; `response._meta` (`api_request_timestamp`). Also read `util.parse_timestamp` (keeps microseconds, normalizes offsets) and `services/ledger.deadline_sweep` (payload carries ids/counts only, no timestamps) plus `derive.py:245-260` (`oldest_unexpended_vintage_at` stored as a `datetime`, rendered by the same path).
- (c) Adjustments: stated the rule as a rendering rule and explicitly said the *instant* (not the rendering) drives comparisons, because `parse_timestamp` retains microsecond precision that `iso_ms` truncates — a claim that timestamps are "stored to millisecond precision" would have been a new mismatch. Widened the enumeration beyond §2.4's own clock-written list to include client-supplied (`requested_due_at`) and computed report timestamps, since those flow through the same formatter and a narrower sentence would have implied they render differently.

Edit 2 — §3.7 credit-claim amount fields
- (a) Subject: validation and valuation contribution of `improvement_value_cents` / `annual_tax_contribution_cents` on claim filing.
- (b) Paths enumerated: `grep -rn "improvement_value|annual_tax|contribution_years|claimed_credit_cents" implementation/` -> single write path `routes/applications.py:203-260` (`create_credit_claim`; `required=` and `minimum=` both keyed off `credit_type`), the validator semantics in `util.Body.integer`/`_get` (explicit `null` counts as absent; out-of-range -> `ERR_INVALID_REQUEST`), the only consumer `services/calc.credit_claim_value:91-108` (`or 0` coalescing, so `None` and `0` are indistinguishable under both `NOMINAL` and `PRESENT_VALUE`), and `serializers.CREDIT_CLAIM_FIELDS:142-145`. Confirmed no PATCH/update path for claims and that `decide_credit_claim` never re-reads the amount fields (it uses `claimed_credit_cents`).
- (c) Adjustments: scoped "contributing nothing" to *the valuation* rather than saying the omitted field is stored as 0 — an absent field persists and serializes as `null` (`Body.integer` default `None`), so a "stored as zero" phrasing would have been a new mismatch. Kept the negative-value rule stated for "either amount field" since `minimum` is 1 or 0 depending on `credit_type` but negative fails in both branches.

## Step 9: Complete PRD — 2026-09-02T04:05:00.000Z

Done. `workspace/PRD_COMPLETED.md` written as a minimal in-paragraph patch over `PRD_FINALIZED.md`. No sections added, no paragraphs added — every change is an inline insert or revision inside an existing sentence.

**Source vs completed**
- `PRD_FINALIZED.md`: 446 lines / 94,628 chars
- `PRD_COMPLETED.md`: 446 lines / 99,763 chars — char delta **+5,135**
- 24 lines touched, 29 distinct changes

**Counts:** 25 ambiguity-pins, 4 mismatch-revisions.

**Changes**
- §2.1 — insert — ambiguity — clock endpoint, though auth-exempt, still rejects a present non-blank `X-User-Role` outside the six roles with `ERR_UNAUTHORIZED` — `implementation/middleware.py:55-67`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + twenty uppercase letters/digits — `implementation/response.py:15-16`
- §2.2 — insert — ambiguity — `api_request_timestamp` reads wall time, not the logical clock — `implementation/response.py:22`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` -> `ERR_INVALID_REQUEST`; empty string falls back to default — `implementation/response.py:54-67`
- §2.3 — insert — ambiguity — server insertion order is the final tie-break on every ordering, including the three named departures — `implementation/db.py:51-53`, `implementation/services/derive.py:112-113`
- §2.7 — revise — mismatch — `ERR_INVALID_REFERENCE` also fires when filing a development application (PRD enumerated only three cases) — `implementation/routes/applications.py:67-69`
- §2.7 — insert — ambiguity — out-of-enum filter -> `ERR_INVALID_REQUEST`; empty filter treated as absent; unnamed query params ignored — `implementation/helpers.py:115-133`
- §2.10 (4) — insert — ambiguity — an explicit `null` counts as absent everywhere — `implementation/util.py:144-150`
- §2.10 (4) — insert — ambiguity — absent body = empty object; non-object/unparseable body -> `ERR_INVALID_REQUEST` — `implementation/helpers.py:44-51`
- §2.11 — insert — ambiguity — categories are version-bumped unconditionally by assessment/payment/deferral/expenditure/refund, but only on actual change by the credit re-assessment and the sweep — `implementation/services/derive.py:266-267`, `implementation/services/assess.py:125,140`, `implementation/services/ledger.py:177`
- §3.2 — insert — ambiguity — `horizon_start_year`/`horizon_end_year` required — `implementation/routes/studies.py:329-330`
- §3.2 — insert — ambiguity — the four projection inputs are optional and default to 0 — `implementation/routes/studies.py:333-336`
- §3.2 — insert — ambiguity — `planned_facility_cost_cents` and `planned_capacity_demand_units` required — `implementation/routes/studies.py:337,339`
- §3.2 — insert — ambiguity — re-allocating a `VALID` component leaves schedule lines' fee and version untouched — `implementation/routes/studies.py:476-477`
- §3.3 — insert — ambiguity — creating a line on a non-`VALID` component returns `ERR_COMPONENT_ALLOCATION_STALE` — `implementation/routes/studies.py:510-511`
- §3.5 — insert — ambiguity — revising an already-`STALE` component is quiet: re-enters `STALE`, no cascade re-fires — `implementation/routes/studies.py:437,447`
- §3.7 — insert — ambiguity — `ERR_CREDIT_CATEGORY_NOT_IN_STUDY` also covers an unresolvable code and a program with no `EFFECTIVE` study — `implementation/routes/applications.py:231-240`
- §3.7 — insert — ambiguity — `valuation_method` is required — `implementation/routes/applications.py:209`
- §3.7 — insert — ambiguity — credit-approval re-assessment prices against the pinned study, stamps `reassessed_at`, leaves pin/`reassessment_required`/`collection_status`/`paid_cents` alone — `implementation/services/assess.py:129-141`
- §3.8 — insert — ambiguity — payment reaches every category named by an assessed line, including a zero-net line that produced no ledger row — `implementation/routes/applications.py:158-159`
- §3.8 — insert — ambiguity — deferral execution does not recompute `fund_posture` — `implementation/routes/applications.py:400`
- §3.9 — insert — ambiguity — `EXPENDITURE`/`REFUND` rows stamp `vintage_at` from the clock, and a `REFUND` row copies the source row's `development_application_id` — `implementation/services/ledger.py:57-68,94-106`
- §3.9 — revise — mismatch — post-expenditure `oldest_unexpended_vintage_at` spans `OPEN`/`PARTIALLY_EXPENDED`/`REFUND_DUE`, not just "eligible" rows — `implementation/services/derive.py:11,191-199`
- §3.9 — insert — ambiguity — the expenditure endpoint returns the created `EXPENDITURE` row — `implementation/routes/programs.py:193-194`
- §3.9 — insert — ambiguity — refund `reason` capped at 500 characters — `implementation/routes/fund.py:48`
- §3.9 — insert — ambiguity — the refund endpoint returns the created `REFUND` row, not the source collection — `implementation/routes/fund.py:55-56`
- §3.9 — revise — mismatch — sweep's `at_risk_category_ids`/`refund_due_category_ids` name every category currently in that posture (not only ones this pass moved); `refund_due_entry_ids` come back in vintage order — `implementation/services/ledger.py:132-181`
- §3.9 — revise — mismatch — program-level `earliest_deadline_at` is the minimum of the per-category values, not a sum — `implementation/services/report.py:96-97,116`
- §3.9 — insert — ambiguity — annual report read's `filed_late` is a live clock verdict while unfiled and freezes at the filed value afterwards, where `report_status` becomes `FILED_ON_TIME`/`FILED_LATE` — `implementation/services/report.py:99-106`

Cross-check note: all 43 impl routes map 1:1 to the §4 table, and the archived test runs (`results.1-8.json`) are 102/102 passing, so no impl behavior was inferred from a failing path.
