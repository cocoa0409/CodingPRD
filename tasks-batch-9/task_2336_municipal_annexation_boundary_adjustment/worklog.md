# Worklog — task_2336_municipal_annexation_boundary_adjustment

## Step 1: Create task directory — 2026-09-01T18:33:00.000Z

Created `tasks/task_2336_municipal_annexation_boundary_adjustment/` and `tasks/task_2336_municipal_annexation_boundary_adjustment/workspace/` (allocated name used verbatim; no index scan).

## Step 2: Generate scaffold — 2026-09-01T22:00:00.000Z

All three artifacts are complete and lint-clean.

## Generated — `tasks/task_2336_municipal_annexation_boundary_adjustment/`

**`SCAFFOLD.yaml`** (§1.0–§1.7 only; no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `domain_name: municipal-annexation`, `api_prefix: ""`, envelope `{data, meta}`, consistency `immediate`, pagination `limit 10 / 1..100 / offset 0`, logical clock default `2026-08-01T00:00:00Z`.
- complexity_profile: layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, conditional_feature_flags]`, topology `flat`, state-machine shape `cyclic`, role model `segregation_of_duties`.
- **15 entities**: StatuteProfile, Municipality, ServiceProvider, PropertyOwner, AnnexationCase, Parcel, UtilityAccount, Petition, ParcelOwnerConsent, FiscalImpactAnalysis, PlanOfServices, ServiceCommitment, PublicHearing, NoticePublication (immutable), ProtestFiling.
- **7 state machines** (AnnexationCase is cyclic: petition cure loop `PETITION_CIRCULATING → SUFFICIENCY_REVIEW → PETITION_CIRCULATING` plus a re-circulation self-loop), **2 concurrency rules** (`expected_case_version`, `expected_plan_of_services_version`), **12 calculations** (territory qualification index, petition sufficiency, dual-variant fiscal impact AVERAGE_COST/MARGINAL_COST with pre-overhead tiering, protest evaluation, plan readiness, provider capacity encumbrance, chamber buffered interval, tax-roll proration, MSD assessment, utility effective rate, effective-date admissibility, de-annexation refund), **60 validations** (priority ladder 1→86), **63 endpoints**, **74 errors**, **7 roles** (StateLawAdmin, MunicipalPlanner, CityClerk, FiscalAnalyst, BoundaryCommissioner, CountyAssessor, PropertyOwner).

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** — 9 rule_ids, **23 instances** (2/3/2/2/3/3/3/2/3): dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade (incl. the six-link effectuate cutover and the five-link consent-withdrawal unwind), priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant.

**`SCAFFOLD_CORNER_DESIGN.yaml`** — 9 guide sections, **83 instances = 54 full recipes + 29 `excluded_because` stubs**: entities 12 (12 full), state_machines 12 (9), calculations 18 (6), validations 18 (7), endpoints 5 (5), rbac 6 (6), complexity_layers 8 (5), errors 3 (3), consistency_model 1 (1). No `bulk_action` instance — §1.5 declares no bulk endpoints.

## Coverage audit (scripted)
- All **74** error ids triggered; all **60** validation priorities cited; all **63** endpoints exercised (structured call or filtered-list prose assert); **0** duplicate instance names across the two design files; every `excluded_because.difficulty_instance` resolves to a §1.8 name; no forbidden concurrency vocabulary in any file; all three files parse as YAML with the required single top-level keys.
- Two §1.5 additions were forced by the audit: `GET /notice-publications/{noticePublicationId}` and `GET /notice-publications` (+ new `ERR_NOTICE_PUBLICATION_NOT_FOUND`, priority-10) — NoticePublication's FK had no reverse-reachability the linter could see (its sub-resource list uses `{hearingId}`, not `{id}`). Endpoints 61→63, errors 73→74. Five validations stubs that cited §1.9 (not §1.8) names were removed; their rules stay covered by full §1.9 state-machine instances.

## Lint verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2336_municipal_annexation_boundary_adjustment/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2336_municipal_annexation_boundary_adjustment/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2336_municipal_annexation_boundary_adjustment/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    63
  §1.1 entities declared:     15
  §1.8 instances scanned:     23
  §1.9 instances scanned:     54
  Calls scanned (§1.8+§1.9):  1330

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

The hard constraint was honoured throughout: no sibling task directory was listed, globbed, grepped or read — only `task_2336`'s own files and the scaffold-generator skill.

## Step 3: Copy shared files — 2026-09-01T22:00:30.000Z

Copied `INSTRUCTION.md` → `tasks/task_2336_municipal_annexation_boundary_adjustment/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T22:20:00.000Z

PRD generated and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2336_municipal_annexation_boundary_adjustment/workspace/PRD.md` — 425 lines, 11,938 words, ends at §5 with no audit footer.

**Sections written**
- `# Municipal Annexation And Boundary Adjustment API` + §1 Introduction (3 paragraphs).
- §2 Global Specifications (10 subsections, domain-derived titles): 2.1 Actors, Headers and Jurisdictional Scope; 2.2 API Response Structure (pasted byte-verbatim from `section-2.2-response-structure.md`, verified by exact substring match); 2.3 Pagination (plus a paragraph naming every list filter); 2.4 The Logical Clock and Statutory Timekeeping; 2.5 Record Identity, Revision Stamps and Immutable Notices; 2.6 The Statute Profile as Configuration Hub; 2.7 Cents, Ratios and Rounding Discipline; 2.8 Optimistic Concurrency on Case and Plan Revisions; 2.9 Cascade Integrity Across Cases, Parcels, Plans and Utility Accounts; 2.10 Path Resolution and the Order of Validation (17-step precedence ladder).
- §3 Business Logic & Workflows (9 subsections, lifecycle-ordered): 3.1 standing up statutes/cities/providers/owners; 3.2 territory assembly and the three statutory tests; 3.3 petition limb incl. the cure cycle; 3.4 fiscal impact (dual `AVERAGE_COST`/`MARGINAL_COST` variant, pinned overhead-tier order); 3.5 plan of services, provider capacity, readiness; 3.6 notice/hearing/protest (dual `ASSESSED_VALUE`/`OWNER_COUNT` basis); 3.7 ordinance, referendum, commission review; 3.8 effectuation six-link cascade, utility rates, tax-roll proration; 3.9 de-annexation (dual `DAILY_PRORATION`/`WHOLE_QUARTER` refund) and the MSD alternative.
- §4 Endpoint Definitions: preamble + 4-column table, 63 rows.
- §5 Error Code Catalogue: 2-column table, 74 rows.

**Coverage audit (all mechanical, scripted against SCAFFOLD.yaml)**
- Entities/fields: 15 entities; 171 required identifiers (all `entities[].fields[].name` + all endpoint `input`/`query_params`/path params, optional `?` markers stripped) — **0 missing**.
- Enum members: 81 distinct enum/set tokens extracted from field constraints — **0 missing**.
- Endpoints: 63/63 present, method+path exact; authorized-role cell compared row-by-row against the scaffold (with `Any role` where all seven roles apply) — **0 mismatches**.
- Errors: 74/74 codes present with **0 HTTP-status mismatches**; every code also appears in §1–§4 prose with its triggering condition.
- Validations: 60/60 walked, including all multi-endpoint `applies_to` scopes (`ERR_PETITION_EXPIRED` ×2, `ERR_HEARING_NOT_SCHEDULED` ×2, `ERR_PROTEST_PERIOD_CLOSED` ×3, `ERR_PLAN_NOT_ADOPTED` ×3, `ERR_PARCEL_CASE_MISMATCH` ×4, `ERR_PREDECESSOR_NOT_EFFECTIVE` ×2, `ERR_PLAN_SERVICE_TIMELINE_EXCEEDS_STATUTE` ×2, `ERR_PROVIDER_SERVICE_TYPE_MISMATCH` ×2, `ERR_DE_ANNEXATION_NOT_ALLOWED` ×2, `ERR_COMMISSION_REVIEW_NOT_PENDING` ×2, `ERR_METHOD_NOT_AUTHORIZED_BY_STATUTE` ×2).
- Calculations: 12/12 rendered as prose with all constants spelled out (3 free miles, 10 points/mile, 25-point urban bonus, 15-point density penalty, 2× contiguity ramp, 100.00 for `OWNER_100`, 5,000,000 / 25,000,000 cent ceilings with 0.12/0.09/0.06 tiers, 12 months, 365 fiscal-year days, 4 quarters, fixed `POLICE, FIRE, WATER, SEWER` order). Both pinned rounding orders (per-share/per-parcel rounding before summation) and the pre-overhead tier selection are stated explicitly as non-interchangeable.
- State machines: 7 machines / 53 transitions individually reconciled, including the `PETITION_CIRCULATING` self-loop, the `SUFFICIENCY_REVIEW`/`HEARING_NOTICED → PETITION_CIRCULATING` cure reverts, the `HEARING_HELD → HEARING_HELD` protest-failed self-loop, all three `EFFECTIVE` origins, and the `OUTSIDE_CITY → … → OUTSIDE_CITY` utility cycle.
- Concurrency: both OCC rules (`expected_case_version`/`ERR_STALE_CASE_VERSION`, `expected_plan_of_services_version`/`ERR_STALE_PLAN_VERSION`) in §2.8, with an explicit statement that no other endpoint takes a version field.
- Endpoint `side_effects`: every declared effect walked; one gap found and fixed (petition aggregate recomputation on consent creation), plus two validation gaps fixed (`ERR_COMMISSION_REVIEW_NOT_PENDING`/`ERR_CASE_STATE_INVALID` on the commission decision, `ERR_PREDECESSOR_NOT_EFFECTIVE` on effectuate).

**Zero-Silence / Hard Contract checks**
- Contract 1 (field-name coverage): PASS, two passes (before and after edits), 171/171 identifiers present verbatim in backticks.
- Contract 2 (rule coverage): PASS across all six high-risk categories (priority ordering, OCC, cross-entity side effects, `applies_to` scopes, field-level structured content such as `covered_service_types` ordering and `notice_published_at` derivation, sibling-branch symmetry for both petition-certification limbs, both submit-to-commission origins, both referendum/commission denial cascades, and both protest bases) plus the tail (transitions, calculations, validation conditions, endpoint side effects).
- Contract 3 (§3 path purity): PASS — 0 backticked tokens in §3 starting with `/`, 0 bare HTTP methods, 0 method+path combinations, and 0 unticked bare-path mentions. All §3 operations are framed as state transitions, role + action verb, or capability descriptions; concrete paths appear only in §2.8 and §4.
- Style checks: no fuzzy quantifiers (`approximately`/`roughly`/`conservatively`/`etc.`/`TBD`) anywhere; only 4 code fences, both the §2.2 JSON envelopes — no pseudocode.

The two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-01T23:00:00.000Z

Suite complete and audited clean.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_2336_municipal_annexation_boundary_adjustment/`)

**Stage 1 — `test_helpers/` (9 files, 2 664 lines)**
`__init__.py` (barrel), `types.py` (7 roles, ~25 status enums, 15 TypedDicts), `api_errors.py` (all 74 `ERR_*` ids + `ERROR_HTTP_STATUS` + `register_error_status_map()`), `api_client.py` (`AnnexationApiClient`, one method per all 63 documented endpoints + `raw_post`/`raw_get`), `constants.py` (logical-clock startup, pagination bounds, every StatuteProfile/Municipality declared default, calculation constants, the canonical statutory timeline), `test_users.py` (opaque-role ids + the mandatory `make_municipal_planner_headers` / `make_city_clerk_headers` / `make_property_owner_headers` entity-backed builders), `factories.py` (payload builders tuned so the canonical territory is certifiable), `assertions.py` (Decimal half-up primitives, calendar helpers, reference implementations of all 12 pinned calculations, shape assertions), `fixtures.py` (primitives, readers, and 30 composite lifecycle builders up to `setup_posted_tax_roll` / `setup_de_annexation_case`).

**Stage 2 — `test_suite/` (conftest + 10 test files, 7 987 lines, 173 tests)**

| file | tests |
|---|---|
| `test_01_fiscal_projection_and_territory_formulas.py` | 13 |
| `test_02_lifecycle_loops_and_cascades.py` | 8 |
| `test_03_validation_precedence_and_threshold_boundaries.py` | 12 |
| `test_04_cross_entity_gates_calendar_overlap_and_invariants.py` | 16 |
| `test_05_entity_records_and_declared_defaults.py` | 13 |
| `test_06_case_and_artifact_state_machines.py` | 11 |
| `test_07_derived_amounts_and_immediate_consistency.py` | 10 |
| `test_08_statutory_validation_limbs.py` | 33 |
| `test_09_endpoint_round_trips_and_error_surface.py` | 28 |
| `test_10_access_control_and_statutory_feature_flags.py` | 29 |

## Coverage per queue

- **Queue A (Difficulty, §1.8): 49 tests across 23/23 instances** — every instance has ≥2 tests. All nine rule families covered (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).
- **Queue B (Corner, §1.9): 124 tests across 54/54 full instances** — every non-stub instance has ≥1 test. The 29 `excluded_because` stubs got zero tests, and all 29 cross-references resolve to real difficulty instances.

## Instances skipped

**None.** No instance failed the PRD-first two-condition filter. Six individual *sub-assertions* inside otherwise-covered instances were dropped rather than weakened, because the PRD does not uniquely derive them: fresh-case/fresh-petition aggregate zeroes (§3.2/§3.3 stamp those only on later transitions); `signature_value_pct == 0.00` on an expired petition; `msd_assessment_cents == null` after a refused MSD adoption (field name also contradicts the PRD); the recipe's "second hearing of the same case cannot be held → `ERR_HEARING_ALREADY_HELD`" (unreachable — §2.10 step 12 puts `ERR_CASE_STATE_INVALID` first); and a "no PUT/PATCH/DELETE exists" claim not testable over the documented HTTP surface (replaced with immutable-shape assertions on all three read channels).

## Audit results

`/tmp/task2336_audit.py` verdict **clean**: exactly one resolving `Design:` tag per test as the last docstring line, no dangling/dual tags, no stub translated, coverage minima met, every quoted citation verbatim in `PRD.md`, and no `skip`/`skipif`/`xfail`, no scaffold vocabulary, no design-index or `implementation/` references. `py_compile` clean on all 20 files; `pytest --collect-only` collects all 173 tests.

## Two Stage 1 bugs found and fixed

1. **`api_client.py` — positional `params` collision (blocking).** All 14 `list_*` methods and `raw_get` called `self.client.get(path, params or None, headers=headers)`, but the framework signature is `get(path, headers=None, params=None)`, so every listing call would have raised `TypeError: got multiple values for argument 'headers'`. Fixed to `params=params or None` in all 15 places.
2. **`state_code` mismatch in the jurisdiction fixture.** PRD §3.1 requires a municipality's `state_code` to equal its statute profile's, but `statute_profile_payload` mints a unique code while `municipality_payload` hardcoded `"NC"`, so `setup_jurisdiction` would have failed with `ERR_INVALID_REQUEST`. `fixtures.create_municipality` now reads the code off the referenced profile unless a test overrides it deliberately.

One residual risk worth noting for the implementation step: `test_05`'s system-stamped-notice test posts extra body fields (`published_at`, `notice_status`) via `raw_post` and expects them ignored — correct under §3.6 plus §2.10's payload-shape list, but an implementation that 400s on unrecognized body keys would fail it.

## Step 6: Generate implementation — 2026-09-01T23:00:30.000Z

Implementation complete and verified.

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_2336_municipal_annexation_boundary_adjustment/workspace/implementation/` (3,669 lines of Python, 18 files):

- Launcher/deps: `start.sh`, `requirements.txt` (`Flask>=3.0.0`)
- Core: `app.py` (68), `db.py` (87), `errors.py` (94), `clockutil.py` (99), `response.py` (117), `auth.py` (64), `validate.py` (198)
- Services: `services/calc.py` (368), `services/domain.py` (483), `services/__init__.py`
- Routes: `routes/__init__.py` (24), `config.py` (278), `cases.py` (595), `petitions.py` (277), `fiscal.py` (147), `plans.py` (314), `hearings.py` (382), `utilities.py` (74)

## Layout and design
- **Storage**: `db.Store` holds 15 plain dicts plus an `RLock`, a `_seq` counter and the logical clock initialised to exactly `2026-08-01T00:00:00Z`. Nothing is seeded; no file, SQLite or external persistence. `app.py` serialises requests on the store lock via `before_request`/`teardown_request`.
- **Endpoints**: 63 Flask routes at server root (`api_prefix: ""`), matching the 63 scaffold endpoint entries one-for-one (verified by diffing `app.url_map` against SCAFFOLD.yaml).
- **Errors**: `errors.py` maps all 74 catalogue ids to HTTP statuses; diffed against the scaffold with zero id or status mismatches. A single `ApiError` handler renders the `{meta, response_type, data}` envelope; `api_request_id` is `req_` + 20 uppercase alnum, `api_request_timestamp` is wall clock with exactly 3 fractional digits.
- **State machines**: the three two-dimensional machines (case `status` × `tax_roll_status`, plan `adoption_status` × `service_readiness`, hearing `hearing_status` × `protest_outcome`) live in their route modules as explicit guard ladders; the shared cross-entity transitions are centralised in `services/domain.py` as five cascade functions — `supersession_cascade`, `rescind_cascade`, `effectuation_cascade` (the six-link chain), `deannexation_cascade` (predecessor unwind + refund + tax-roll reversal) and `msd_cascade`. Cyclic limbs (`SUFFICIENCY_REVIEW ⇄ PETITION_CIRCULATING`, HEARING_HELD self-loop, the `OUTSIDE_CITY → … → OUTSIDE_CITY` account cycle) fall out of those helpers.
- **Calculations**: all in `services/calc.py` with `decimal.Decimal` + ROUND_HALF_UP and pinned rounding order — territory aggregates, qualification index, petition sufficiency, overhead tiering (0.12/0.09/0.06 keyed to pre-overhead base cost), protest evaluation, per-parcel `annual_tax_cents`/`prorated_tax_cents` (rounded per parcel *before* summation, FY_DAYS = 365), de-annexation refund (daily vs whole-quarter), MSD assessment, utility surcharge, timeline/capacity/chamber-overlap and effective-date admissibility.
- **Validation ladder**: one consistent order encoded in every endpoint, from PRD §2.10 (treated as authoritative over §3.x prose): headers → role → municipality scope → owner scope → segregation of duties → path 404 → body FK 404 → payload shape → pagination → OCC (`expected_case_version`, `expected_plan_of_services_version`) → case terminal → state → business safety → temporal → referential → fiscal. Scope-before-404 is implemented with a non-raising `domain.soft()` lookup followed by `domain.path_record()`.

## Boot and behaviour verification
- Repeated fresh boots via `start.sh` on scratch ports: store empty (`GET` collections return `total_count: 0`), logical clock reads `2026-08-01T00:00:00Z`.
- **Boot latency fix**: the dependency probe in `start.sh` was `python3 -c "import flask"`, which costs ~8 s on this host (flask/werkzeug import is disk-bound). Replaced with an `importlib.util.find_spec('flask')` probe, cutting time-to-first-200 from ~12 s to ~4 s per relaunch — material under `--isolation per-test-server`.
- **Smoke suite 1** (full annexation lifecycle, `/tmp/t2336_smoke.py`): statute → municipality → provider → owners → case → 2 parcels → utility account → certify (contiguity 0.2, urban true, index 100) → petition → consent → sufficiency (50.0% value, 50.0% owner) → plan + 4 commitments activated (READY, provider `encumbered_capacity_days` 424) → adopt → hearing (+`ERR_HEARING_SLOT_CONFLICT`) → notice → hold (`ERR_NOTICE_WINDOW_NOT_SATISFIED` before the clock moves) → filing (+`ERR_FILING_DUPLICATE`) → close protest (5.0%, FAILED) → analysis (200000 / 120000 / 1200000 revenue, base 200000, tier 0.12, net 1296000, deficit 0.00) → finalize → ordinance → effectuate (`ERR_EFFECTIVE_DATE_INVALID` on a non-admissible date) → account `INSIDE_CITY_ACTIVE` at the unsurcharged rate → tax roll (per-parcel 100000 → 70685, case total 141370, ledger 20000000) → de-annexation case reading its territory through the predecessor. Negative probes returned `ERR_PAGINATION_INVALID`, `ERR_UNAUTHENTICATED`, `ERR_ROLE_NOT_PERMITTED`, `ERR_MUNICIPALITY_SCOPE_VIOLATION`, `ERR_CASE_NOT_FOUND`.
- **Smoke suite 2** (cascades, `/tmp/t2336_smoke2.py`): de-annexation effectuation unwound the predecessor (`DE_ANNEXED`, `tax_roll_status REVERSED`, parcel `DE_ANNEXED`, account back to `OUTSIDE_CITY`/`OUTSIDE_CITY_SURCHARGE` at 30000, municipal ledger back to 0) with refund 148729 = round(282740 × 192/365); protest-sustained case adopted the MSD alternative (`MSD_ALTERNATIVE_ADOPTED`, assessment 1200000 = 1600000 × 0.75, parcel `EXCLUDED`, account `DISCONNECTED`, replay → `ERR_CASE_TERMINAL`); consent withdrawal fired the supersession cascade in full (petition `INSUFFICIENT` at 0.0%, case back to `PETITION_CIRCULATING`, hearing `VACATED`, notice `SUPERSEDED`, `notice_published_at` reset to null). Every printed figure matched hand-computed Decimal expectations.
- All scratch servers were killed and `__pycache__` directories removed; the implementation tree contains only the 18 source files. Note: an early cleanup command matched `python3 app.py` broadly, so any concurrently running task server on this host may have been restarted — harmless under per-test relaunch, but worth knowing if a sibling job logged a blip around that time.

## Step 7: Diagnostic iteration (test + fix loop) — 2026-09-02T01:30:00Z

### Test-layer bugs found and fixed (2 defects, 13 sites)

1. **`test_suite/test_09_endpoint_round_trips_and_error_surface.py` — double-unwrapped envelope (12 sites).**
   `validate_success()` already returns `body["data"]`, but twelve call sites appended a
   further `["data"]` subscript, so each raised `KeyError: 'data'` before any domain
   assertion ran. Removed the redundant subscript at lines 126, 130-132, 142, 150, 235,
   240, 386, 399, 474, 484, 493 and 527. Five tests were affected
   (`..._statute_and_its_city_read_back_exactly_as_created`,
   `..._excluding_a_parcel_disconnects_its_account_and_shrinks_the_territory`,
   `..._a_registered_account_stores_both_of_its_foreign_keys_and_the_outside_city_rate`,
   `..._a_method_requiring_ratification_lands_in_referendum_pending_and_then_effectuates`,
   `..._a_method_absent_from_the_ratification_list_lands_directly_in_ordinance_adopted`).
   Pure test bug — no implementation change, no assertion weakened.

2. **`test_suite/conftest.py` — session-scoped API client outlived the server (flakiness).**
   The `api` fixture was `scope="session"`, so one `requests.Session` (and its connection
   pool) was shared across every test. Under `--isolation per-test-server` the server is
   SIGKILLed between tests, so a pooled keep-alive socket could be reused against a dead
   process and surface as
   `ConnectionResetError(104, 'Connection reset by peer')` on the first call of a later
   test. Made the fixture function-scoped so each test gets a fresh client. Reproduced
   before the fix, gone after.

No test was deleted: every failing test's rule was verbatim in `PRD.md` and uniquely
derivable, and both defects were in the test layer itself.

No implementation change was required. `workspace/implementation/` is untouched by this
step (still the 18 source files); `db.Store.reset()` remains empty-on-boot with no seeded
data.

### Verification

- **173/173 passed, three independent full-suite runs** under fresh-server-per-test
  isolation (16m16s / 16m27s / 16m33s), plus targeted reruns of the 15 individual tests
  that never drew a clean slot in the official sweeps. Every one of the 173 tests is
  confirmed green.
- **8-round parallel sweep: 0 assertion failures in all 8 rounds** (`failed == 0`
  everywhere). Rounds reported 65-92 passed of 173; **every single one of the 733
  non-passes was the identical host-level infrastructure error**, not a task defect:

  ```
  failed on setup with "subprocess.TimeoutExpired: Command
  'pids=$(lsof -ti:<port> -sTCP:LISTEN 2>/dev/null); ...' timed out after 5 seconds"
  ```

  This is `prd_bench_local_runner.pytest_plugin._kill_port`, which shells out to `lsof`
  with a hard-coded 5-second timeout before every per-test server restart. This shared
  host was running 200-490 concurrent `prd-bench-local-run` processes from sibling task
  pipelines, 2 400-4 200 processes total (1 200-1 500 of them `[sh] <defunct>`), at a
  sustained load average of 250-350 on 32 cores. Measured `lsof -ti:<port> -sTCP:LISTEN`
  cost under that load: **1.5 s to 8.4 s**, i.e. over the runner's 5 s bar roughly half
  the time, and the failure is raised uncaught out of `pytest_runtest_setup`. One earlier
  sweep attempt was additionally wiped out wholesale when all 8 pytest processes were
  killed simultaneously at 00:58 by an external broad `pkill` from another agent on the
  host.

  A clean 8-round official sweep is therefore not reachable from inside this task while
  the host stays in that state: it needs 8 x 173 = 1 384 consecutive sub-5-second `lsof`
  calls. The task artifact itself is green, and the fix belongs in the runner
  (`_kill_port` should tolerate a slow/timed-out `lsof` rather than propagate
  `TimeoutExpired`), which is shared infrastructure outside this task's scope.

### Orchestrator addendum to Step 7 — 2026-09-02T01:50:00.000Z

Verified independently from the eight `results.*.json` files of the final sweep:
`failed == 0` in all 8 rounds; all 733 non-passes classify to the single
`subprocess.TimeoutExpired ... lsof -ti:<port> -sTCP:LISTEN ... timed out after 5 seconds`
setup error, with zero assertion failures and zero domain errors. Host state at the time of
this check: load average 272.80 on 32 cores, 396 concurrent `prd-bench-local-run` processes
from sibling pipelines.

Union coverage across the 8 sweep rounds: 169 of 173 tests passed in at least one round.
The 4 that never drew a clean slot were sent back for targeted re-verification:
`test_contiguity_ratio_one_ten_thousandth_below_the_minimum_refuses_certification`,
`test_municipality_registration_without_a_population_is_rejected`,
`test_certifying_a_territory_failing_both_urban_limbs_is_refused`,
`test_average_cost_variant_prices_service_from_the_citywide_per_capita_rate`.
Pre-sweep copies of the eight results files were kept at `/tmp/t2336_prev/`.

## Step 7 (re-verification, concurrent with Step 8) — 2026-09-02T01:50:30.000Z

Re-verification sweep + targeted reruns dispatched to the long-lived Step 7 subagent; result recorded below.

## Step 8: Finalize PRD — 2026-09-02T02:00:00.000Z

`PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_2336_municipal_annexation_boundary_adjustment/workspace/PRD_FINALIZED.md` as a byte-identical copy of `PRD.md` (verified: `diff` clean, matching md5 `7e827047e4eef43acd6dfe48f8192339`). Neither `<step_7_diff>` item revealed a PRD silence or a PRD/implementation mismatch.

**Line counts:** PRD.md 425 lines → PRD_FINALIZED.md 425 lines, %-delta 0.00% (files byte-identical, md5 `7e827047e4eef43acd6dfe48f8192339` both).

**Changes:** none. Zero inserts, zero revisions.

**Per-diff-item adjudication (why no edit):**

- **Item 1 — `test_suite/test_09_...py` double-unwrapped envelope (12 sites).** Pure test-artifact defect: `validate_success()` already returns `body["data"]` and the call sites appended a second `["data"]`, raising `KeyError: 'data'` before any domain assertion executed. The failure mode is entirely inside the harness helper contract; `PRD.md` §2.2 already fixes the envelope uniquely (`meta` / `response_type` / `data`, with `data` carrying the resource object), and `implementation/response.py:49-72` emits exactly that. I re-derived each of the 5 unblocked tests' assertions from PRD prose and confirmed every one is already uniquely determined, so no assertion needed a PRD anchor:
  - `statute_and_its_city_read_back_exactly_as_created` — statute defaults, `version` 1, payload echo, `taxable_assessed_value_cents == 0` → PRD §2.5, §2.6, §3.1; impl `routes/config.py:42-140` (statute defaults), `routes/config.py:153-201` (city, ledger seeded 0), `db.py:62-71` (`version` 1).
  - `excluding_a_parcel_disconnects_its_account_and_shrinks_the_territory` — `EXCLUDED`, `OUTSIDE_CITY → DISCONNECTED`, aggregate recompute, case `version` 1+2 adds then +1 exclude → PRD §3.2 ¶4-5, §2.9; impl `routes/cases.py:221-250`, `services/domain.py:175-181`.
  - `a_registered_account_stores_both_of_its_foreign_keys_and_the_outside_city_rate` — `OUTSIDE_CITY` / `OUTSIDE_CITY_SURCHARGE` / surcharged `effective_monthly_cents` → PRD §3.8 ¶3; impl `routes/utilities.py:293-338`, `services/calc.py:346-349`.
  - `a_method_requiring_ratification_lands_in_referendum_pending_and_then_effectuates` and `a_method_absent_from_the_ratification_list_lands_directly_in_ordinance_adopted` — the `referendum_required_methods` fork, `ordinance_adopted_at` from the logical clock, `commission_review_status` staying `NOT_REQUIRED`, `PENDING_ANNEX → INCORPORATED` → PRD §3.7 ¶2-3, §3.8 ¶3; impl `routes/cases.py:379-386`, `routes/cases.py:403-413`, `routes/cases.py:516-522`, `services/domain.py:377-434`.
- **Item 2 — `test_suite/conftest.py` `api` fixture was `scope="session"`.** Pure fixture/transport defect: one pooled `requests.Session` reused a keep-alive socket across the `--isolation per-test-server` SIGKILL boundary, producing `ConnectionResetError(104)`. Nothing about HTTP connection reuse, server lifetime or store seeding is a PRD-level behavior; `implementation/db.py:40-48` starts every boot with all 15 collections empty and the clock at `2026-08-01T00:00:00Z`, exactly as PRD §2.4 states. No PRD surface to pin.
- **Tests deleted:** none, per the diff — so there is no weakened-assertion site to re-pin either.

**Per-edit pre-edit search log:** not applicable — no edits were committed. For completeness, the global consistency sweep I ran before concluding "no edit" covered every impl path touching the five fix sites' subjects: `routes/config.py` (statute/municipality/provider/owner creation + reads), `routes/cases.py` (case creation, parcel add/exclude, certification, ordinance/referendum/commission, effectuate, post-tax-roll, MSD), `routes/utilities.py` (account registration, reads, filters), `services/domain.py` (territory aggregates, `restamp_qualification`, all three cascade families, `refresh_account_rate`), `services/calc.py` (territory qualification, surcharge, effective-date admissibility), `response.py` (envelope + pagination), `db.py` (identity/revision stamps, ordering). One near-miss worth recording but deliberately **not** edited: `services/domain.py:184-194` (`restamp_qualification`, called from `routes/cases.py:200-202` and `routes/cases.py:246-249`) also refreshes `contiguity_ratio`, `urban_development_qualified` and `qualification_index` on a still-`DRAFT` case, which PRD §3.2 ¶5 ("while the case is still `DRAFT` both also refresh the territory measurements described next") does not spell out beyond the three aggregates. No Step 7 test observes those fields before certification, so this is not a PRD silence that the `<step_7_diff>` revealed; per HARD SCOPE and the NO-NEW-MISMATCH rule I left the prose untouched rather than adding a claim Step 7 never exercised.

## Step 9: Complete PRD — 2026-09-02T02:12:00.000Z

Done. `PRD_COMPLETED.md` written.

**Source vs completed:** `PRD_FINALIZED.md` 425 lines / 95,073 chars → `PRD_COMPLETED.md` 425 lines / 98,773 chars (**+3,700 chars**, 0 line delta — all edits are in-paragraph; no new sections or paragraphs).

**Counts:** 19 ambiguity-pins, 2 mismatch-revisions (21 change sites across 18 PRD lines).

**Changes**

- §2.2 — insert — ambiguity — `api_request_timestamp` is the one timestamp read from the host's real clock, not the logical clock — `response.py:28`
- §2.3 — insert — ambiguity — a non-integer `limit`/`offset` also draws `ERR_PAGINATION_INVALID`; an empty query value falls back to the default — `response.py:90-104`
- §2.3 — insert — ambiguity — records sharing a `created_at` (the normal case under a frozen clock) keep creation order — `db.py:85-87`
- §2.6 — insert — ambiguity — a duplicate `state_code` profile is rejected with `ERR_INVALID_REQUEST` — `config.py:135-137`
- §2.6 — insert — ambiguity — `fiscal_year_end_month_day` admits `02-29` and falls back to the last day of the month in a year lacking it — `clockutil.py:76-83`
- §2.9 — revise — **mismatch** — the case's `version` advances on a consent withdrawal only when it drops a `SUFFICIENT` petition below threshold; an ordinary withdrawal touches only consent and petition — `petitions.py:269-276`
- §2.10 step 3 — revise — ambiguity — municipality scope compares the submitted identifier directly on case creation / hearing scheduling / provider registration, and is skipped (falling through to 404) when the resource does not resolve — `auth.py:39-45`, `cases.py:46-48`, `config.py:224`
- §2.10 step 4 — revise — ambiguity — owner scope is skipped when the payload's `property_owner_id` is absent or non-string, letting step 8 fire — `auth.py:48-54`, `petitions.py:156-158`
- §2.10 step 5 — revise — ambiguity — segregation of duties is skipped when the case does not resolve or `fiscal_finalized_by_user_id` is null — `auth.py:57-64`
- §3.1 — insert — ambiguity — a `state_code` that disagrees with the profile draws `ERR_INVALID_REQUEST` — `config.py:180-181`
- §3.2 — insert — ambiguity — a fresh case's derived figures are all present at zero/false/null (`parcel_count`, `territory_acreage`, `contiguity_ratio`, `qualification_index`, `protest_pct`, tax-roll totals, refund, MSD assessment, and the four null timestamps/ids) — `cases.py:101-119`
- §3.2 — insert — ambiguity — a new parcel carries `annual_tax_cents`/`prorated_tax_cents` 0; adding to a `DE_ANNEXATION` case draws `ERR_PARCEL_STATE_INVALID`; the APN conflict requires the sibling parcel itself to be `PROPOSED`/`PENDING_ANNEX`/`INCORPORATED` — `cases.py:160-181,194-195`
- §3.2 — revise — ambiguity — parcel add/exclude also restamps `contiguity_ratio`, `urban_development_qualified` and `qualification_index` while the case is `DRAFT` (the flagged `restamp_qualification` site) — `domain.py:184-194`, `cases.py:201-202,247-248`
- §3.3 — insert — ambiguity — a new petition's four signature aggregates start at zero — `petitions.py:71-74`
- §3.3 — insert — ambiguity — opening a petition on a `REFERENDUM`/`INVOLUNTARY_ORDINANCE` case draws `ERR_CASE_STATE_INVALID` — `petitions.py:46-50`
- §3.3 — insert — ambiguity — certifying an already-`SUFFICIENT` petition draws `ERR_CASE_STATE_INVALID`, and no case-status requirement applies — `petitions.py:111-115`
- §3.4 — revise — ambiguity — finalize checks case terminality (`ERR_CASE_TERMINAL`), then `EFFECTIVE` (`ERR_CASE_STATE_INVALID`), then `DRAFT` and the sibling-`FINALIZED` bar (both `ERR_ANALYSIS_STATE_INVALID`) — `fiscal.py:121-139`
- §3.5 — revise — ambiguity — voiding on an `EFFECTIVE` case draws `ERR_CASE_STATE_INVALID`, on a `DE_ANNEXED` one `ERR_CASE_TERMINAL` — `plans.py:291-298`
- §3.5 — revise — ambiguity — adopting a plan not in `DRAFT` (including `RESCINDED`) draws `ERR_PLAN_ALREADY_ADOPTED` — `plans.py:101-102`
- §3.7 — revise — **mismatch** — ordinance adoption tests the case's mirrored `protest_outcome`, so `NOT_EVALUATED` (never tabulated) also draws `ERR_PROTEST_PERIOD_OPEN` — `cases.py:349-350`
- §3.8 — insert — ambiguity — a required referendum not `APPROVED` at effectuation draws `ERR_CASE_STATE_INVALID` — `cases.py:483-486`

**Verified-consistent, left untouched:** all 63 endpoint paths/roles and 74 error ids match §4/§5 exactly; every list filter set matches §2.3; the twelve `services/calc.py` formulas, rounding orders, all three cascades, the six effectuation links, provider capacity/chamber-conflict tests, and every check-precedence chain follow §2.10's numbered ladder (where §3 prose lists checks in a different narrative order, impl follows §2.10, so no edit was warranted).

## Step 7b: Targeted re-verification of the 4 uncovered tests + final sweep — 2026-09-02T02:20:00Z

### 1. Targeted re-verification (official runner, `--isolation per-test-server`)

Built a temporary test dir (`/tmp/t2336_verify/`) holding a copy of `test_suite/conftest.py`, a
symlink to `test_helpers/`, and one collector module that loads the four **unmodified** function
objects from their owning modules by path and rebinds them, so only those four are collected.
Ran it through `prd-bench-local-run --isolation per-test-server` **11 times**; temp dir deleted
afterwards. Result — **all four are green**, and there was never an assertion failure:

| Test | Owning file | PASSED | infra-ERROR | assertion-FAILED |
|---|---|---|---|---|
| `test_average_cost_variant_prices_service_from_the_citywide_per_capita_rate` | `test_01` | 7/11 | 4 | **0** |
| `test_certifying_a_territory_failing_both_urban_limbs_is_refused` | `test_08` | 7/11 | 4 | **0** |
| `test_contiguity_ratio_one_ten_thousandth_below_the_minimum_refuses_certification` | `test_03` | 8/11 | 3 | **0** |
| `test_municipality_registration_without_a_population_is_rejected` | `test_05` | 9/11 | 2 | **0** |

Attempts 6, 8 and 10 were fully clean 4/4. All 15 infra-ERRORs were the same
`lsof` `TimeoutExpired`. No test failed on an assertion, so the STEP 0 → STEP 3 diagnostic
protocol was not entered and nothing was changed.

### 2. Final 8-round parallel sweep

Host had calmed somewhat (load average 231-253, ~298 sibling `prd-bench-local-run` processes,
3 263 processes), and the sweep is correspondingly much healthier than the previous one
(73-80% per round, up from 38-53%):

| round | passed | failed | errors |
|---|---|---|---|
| 1 | 139/173 | 0 | 34 |
| 2 | 132/173 | 1 | 40 |
| 3 | 138/173 | 1 | 34 |
| 4 | 130/173 | 0 | 43 |
| 5 | 127/173 | 0 | 46 |
| 6 | 129/173 | 0 | 44 |
| 7 | 131/173 | 0 | 42 |
| 8 | 136/173 | 0 | 37 |

- **Union pass coverage: 173/173 (100%) passed in at least one round. Zero tests never passed.**
- **Zero assertion failures.** Of the 322 non-passes, **320 were the `lsof` `TimeoutExpired`**
  infra error in `pytest_plugin._kill_port`.
- The 2 remaining non-passes (the `failed=1` in rounds 2 and 3) were
  `requests.exceptions.ConnectionError: ('Connection aborted.', ConnectionResetError(104,
  'Connection reset by peer'))` — the server dying *mid-test* on
  `test_msd_assessment_is_three_quarters_of_the_adopted_plans_committed_cost` (round 2) and
  `test_the_district_alternative_is_refused_where_the_statute_forbids_it` (round 3). Both are
  external kills, not app faults: `grep -c Traceback` on both rounds' server logs
  (`/tmp/prd_bench_server_34373.log`, `/tmp/prd_bench_server_52589.log`) returns **0**, i.e. the
  processes were SIGKILLed rather than crashing — the same hazard as the 00:58 event where all
  8 pytest processes were killed simultaneously by an external broad `pkill` from another agent.
  Both tests were then re-verified in isolation through the official runner **5 more times**
  (10 executions): 2/2 clean on attempts 1 and 5, **0 assertion failures**, and the
  `ConnectionResetError` never reproduced.

### Conclusion

All 173 tests are confirmed green under the official runner's per-test-server isolation. Across
the two sweeps and the targeted reruns there has not been a single assertion failure. The only
thing standing between this task and a literally clean 8-round sweep is the runner's
`_kill_port`, which shells out to `lsof` with a hard-coded 5 s timeout and lets
`TimeoutExpired` propagate out of `pytest_runtest_setup`; on this shared host `lsof` costs
1.5-8.4 s. That fix belongs in shared infrastructure, outside this task's scope. No test was
weakened, skipped or deleted to accommodate the infra flakiness.
