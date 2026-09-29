# Worklog — task_2685_community_development_financial_institution_certification_lending

## Step 1: Create task directory — 2026-09-04T06:11:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2685_community_development_financial_institution_certification_lending` and its `workspace/` subdirectory. Index 2685 was pre-assigned by the orchestrating command; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold artifacts — 2026-09-04T07:55:00.000Z

Generated `SCAFFOLD.yaml` (§1.0–§1.7), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8) and
`SCAFFOLD_CORNER_DESIGN.yaml` (§1.9) from the verbatim scenario plus the scaffold-generator
skill spec only; no sibling task directory was read. Difficulty level `beyond_expert`.

Final shape: 12 entities, 10 state machines, 2 OCC races, 9 calculations (3 dual-variant),
55 validation rungs, 71 endpoints, 52 error codes, 7 roles (segregation-of-duties role model).
§1.8 carries 9 rules x 2 instances = 18; §1.9 carries 73 instances across the nine sections
(56 full recipes + 17 `excluded_because` stubs citing §1.8).

Fixes applied while linting: pagination reads moved to `meta.total_count` / `meta.has_more`
(list responses put rows in `data` as an array, now documented in `response_envelope`),
undeclared payload keys removed from the computed-/system-field instances,
`reserve_deficit_cents` asserts corrected to 0 on non-charge-off paths, and five single-resource
GETs plus seven flat parent-filtered lists added to §1.5 so every §1.1 FK is reverse-reachable.
`scaffold_lint.py` verdict: clean lint (752 calls scanned).

## Step 2 (orchestrator record): verbatim subagent summary — 2026-09-04T07:58:00.000Z

All three scaffold artifacts for task 2685 are complete and `scaffold_lint.py` reports **VERDICT: clean lint** (752 calls scanned, all §1.8/§1.9 calls conform to §1.5, all §1.1 FKs reverse-reachable).

Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2685_community_development_financial_institution_certification_lending/`):
- `SCAFFOLD.yaml` — 3,095 lines / 164 KB (§1.0–§1.7 only; no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1,801 lines / 115 KB (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4,007 lines / 245 KB (single key `scaffold_corner_design`)
- `worklog.md` updated with a Step 2 entry; `workspace/` intact. No sibling task directory was read at any point.

SCAFFOLD counts (`difficulty_level: beyond_expert`, archetype `compliance_audit` / `ledger_reconciliation`, topology `graph`, state shape `parallel` + cyclic/compound/branching/posture-driven, role model `segregation_of_duties`, consistency `immediate`):
- 12 entities, 10 state machines, 2 OCC concurrency rules, 9 calculations (3 dual-variant), 55 validation rungs (priority 1→84), 71 endpoints, 52 error codes, 7 roles

§1.8 — 9 rules × 2 instances = 18: `dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`.

§1.9 — 73 instances (56 full `test_recipe`s + 17 `excluded_because` stubs, every stub citing a real §1.8 instance): entities 9, state_machines 12, calculations 8, validations 13, endpoints 8, errors 7, rbac 8, cross_cutting_complexity_layers 7, consistency_model 1.

Key corrections made during verification, worth knowing downstream:
- List responses put rows in `data` as a JSON array with `total_count`/`has_more` in `meta` — this is now documented as `response_envelope.pagination_location`, and all §1.9 pagination captures use `$.meta.*` / `$.data[N].*`.
- §1.5 gained 5 single-resource GETs (`/target-markets/{id}`, `/borrowers/{id}`, `/loan-products/{id}`, `/compliance-measurements/{id}`, `/matching-fund-commitments/{id}`) and 7 flat parent-filtered lists, which is what cleared the FK reverse-reachability rule; endpoint count moved 59 → 71 and NOT_FOUND rungs 22/24/25 were widened accordingly.
- `reserve_deficit_cents` is written only by charge-off absorption, so a servicing-run instance that asserted a non-zero deficit was corrected to 0.
- `ERR_MATCH_SHORTFALL` and `ERR_POSTURE_NOT_COMPLIANT` were previously unasserted anywhere; both now have real triggers (a 22-call activation chain in §1.9 errors, and a `resume-draws` follow-up appended to the §1.8 charge-off cascade).

## Step 3: Copy shared files — 2026-09-04T07:58:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-04T08:15:00.000Z

Truncation guard (orchestrator): verified `workspace/PRD.md` is 413 lines, ends at a real section
boundary — the final row of the §5 error-code table (`| ERR_FEDERAL_SOURCE_INELIGIBLE | 422 |`),
not mid-sentence. All expected section headings present (§1 Introduction, §2.1–§2.11 Global
Specifications, §3.1–§3.9 Business Logic, §4 Endpoint Definitions, §5 Error Code Catalogue).
No regeneration needed.

Subagent summary (verbatim):

PRD complete and verified.

**Deliverable:** `/home/ubuntu/github/CodingPRD/tasks/task_2685_community_development_financial_institution_certification_lending/workspace/PRD.md` — **413 lines**, built in eight chunked `cat >>` appends (each verified with `wc -l` + `tail`), ends cleanly on the last row of the §5 table (`| \`ERR_FEDERAL_SOURCE_INELIGIBLE\` | 422 |`). No audit footer, no contract report inside the document.

**Section list**
- §1 Introduction (3 paragraphs: certification as continuous proof, the `/cdfi` arc, the two standing commitments — funded reserve, honest snapshots with stale-read rejection)
- §2 Global Specifications (11 subsections): 2.1 RBAC (7 roles, entity-backed vs opaque identity, 3 segregation-of-duties points) · 2.2 API Response Structure (verbatim fixed block) · 2.3 Pagination · 2.4 Identity/Version/Timestamps · 2.5 Logical Clock · 2.6 Rounding, Money & Rate Units · 2.7 Optimistic Concurrency · 2.8 Rejection Precedence (11-band ladder) · 2.9 Nested Paths & Reverse-Lookup Filters · 2.10 Dual-Variant Determinations · 2.11 Reserve Adequacy, Posture & Cascade Propagation
- §3 Business Logic (9 subsections): 3.1 Lender & accountability structures · 3.2 Certification docket · 3.3 Borrower intake/geocoding/attribution · 3.4 Products & TA programme · 3.5 Origination & pricing chain · 3.6 Disbursement/servicing/delinquency/charge-off · 3.7 Impact ledger · 3.8 Lending measurement & recertification · 3.9 Awards, matching funds & draw control
- §4 Endpoint Definitions — lead paragraph on 201/200 + 71-row, 4-column table
- §5 Error Code Catalogue — 52-row, 2-column table

**Hard Contract 1 — Field-Name Coverage: PASS.** Inventory built programmatically from the scaffold: 153 entity fields + 80 request-body identifiers + 24 query params + 12 path params + 2 OCC fields = **170 unique names**. Pass 1 (whole document, code fences excluded): 0 missing. Pass 2 (stricter — §1–§3 prose only, §4/§5 tables excluded): 0 missing in every group (entity 0/153, body 0/80, query 0/24, path 0/12, occ 0/2). Every name appears verbatim inside backticks in the prose, not merely in the tables.

**Hard Contract 2 — Rule Coverage: PASS.** All 6 high-risk categories: validation priority ordering (§2.8 ladder contains all **52** distinct validation error ids from the scaffold's 55 validation rows, with the two counter-intuitive orderings called out — tier-before-geocoded on underwriting; conflict/overlap-before-bounds on booking and measurement); OCC (§2.7, both rules, both non-optional); cross-entity side effects (§2.11, §3.1, §3.2, §3.6, §3.7, §3.9 — resignation cascade, certification→institution, charge-off 4-link cascade, impact ledger, probation suspension/hold, resume); `applies_to` scopes (all 43 distinct scopes enumerated in §2.8); field-level structured content (all enums, ranges, defaults, conditional-requirement pairs in §3); sibling-branch symmetry (APPROVE/DECLINE, COMPLETED/NO_SHOW, PASS/FAIL, AWARD/REJECT, MATCHED/UNMATCHED, verify/dispute, withdraw-from-PLEDGED vs from-VERIFIED — each pair's differing side-effect set stated). Tail: all **58** transitions across the 9 state machines covered (39 in explicit `A → B` arrow form; the remaining 19 — 5 posture band moves, the UNDER_REVIEW self-loop, 6 delinquency bucket moves, the cure, 3 supersede paths, 2 withdrawals, HELD→PLEDGED, UNGEOCODED→GEOCODE_FAILED — are stated as derivation rules in §2.11, §3.3, §3.6, §3.7, §3.9 where a bare arrow would be misleading); all **9** calculations expressed as prose algorithms with their constants; all endpoint side effects covered.

**Hard Contract 3 — §3 Path Purity: PASS.** 335 distinct backticked tokens in §3; 0 start with `/`, 0 are bare HTTP methods, 0 combine method+path. `/cdfi` occurs 0 times in §3 and no bare `GET/POST/PUT/PATCH/DELETE` word appears there. Paths appear only in §1 (the mount) and §2.7 (the two OCC endpoints, as the skill's example authorises), plus §4.

**Fidelity notes for the worklog** — §4's method/path/role columns were generated from the scaffold and machine-diffed: all 71 rows match order, method, path and role list exactly; all 52 §5 statuses match the scaffold. Two scaffold-internal contradictions required a documented judgement call: `info_requested_reason` on the board-resignation cascade written as `ACCOUNTABILITY_TEST_FAILED` (state-machine table over endpoint text), and `actual_hours` on a `NO_SHOW` close written as `0.00` (two agreeing endpoint statements over the state machine's `null`). The `revision_round < 2` bound on that cascade is stated explicitly. No fuzzy quantifiers, pseudocode or operator syntax in §1–§3. The two withheld design files were never opened.

## Step 6 — Implementation Generation (Python + Flask)

**Output:** `workspace/implementation/` — 18 Python modules, 3187 lines total, plus `start.sh` (executable, guarded install then `exec python3 app.py`) and `requirements.txt` (`Flask==3.0.3`).

**Module list with line counts.** Foundation: `app.py` 58 · `store.py` 149 · `errors.py` 83 · `numeric.py` 49 · `envelope.py` 104 · `auth.py` 84 · `shape.py` 194 · `calc.py` 249 · `services.py` 388. Routes: `routes/__init__.py` 0 · `routes/institutions.py` 142 · `routes/governance.py` 221 · `routes/certification.py` 247 · `routes/borrowers.py` 319 · `routes/loans.py` 292 · `routes/impact.py` 151 · `routes/measurements.py` 159 · `routes/awards.py` 298.

**Endpoint count implemented: 71/71** (31 GET + 40 POST), matching the §4 table row-for-row: institutions 5, governance 9, certification 10, borrowers/products/TA 13, loans 8, impact 6, measurements 6, awards/commitments 14.

**Notable design decisions.**
- *Storage:* process-local Python dicts keyed by UUID inside a single `Store` object; empty on every boot; no seeding, no preload, no SQLite, no disk IO of any kind (grep-verified: the only `seed`/`preload` hits are the comments asserting their absence). Required because the harness runs `--isolation per-test-server` and reboots via `start.sh` before every test.
- *Logical clock:* every entity date/time field reads `store.now()`, never the wall clock; default `2026-08-01T00:00:00Z`, moved only by `POST /cdfi/_clock/set_current_utc`. Timestamps serialise with exactly 3 fractional digits.
- *Exact arithmetic:* all ratio/percentage/money math runs through `fractions.Fraction` and is quantized once with `Decimal` + `ROUND_HALF_UP` (`numeric.rhu`); `float` never touches a monetary or rate value. The two opposite rounding orders the PRD demands are kept distinct: reserve sums exact per-bucket products and rounds once at the end, while match eligibility rounds per commitment and then sums.
- *Rejection precedence:* the 11-band ladder of §2.8 is expressed positionally in each handler — auth, then authz/scope/SoD, then existence, then shape, then concurrency, then state, then business safety, then referential, constraint, temporal, fiscal. To get band 2 ahead of band 3 for resources addressed by a non-institution id, the handler does a *non-fatal* dict lookup to derive the owning institution for `scope()`/`segregation()` and falls through to the 404 only after the scope check. For the same reason `shape.body()` returns `{}` for a non-object payload instead of failing, so body parsing can never pre-empt a scope check.
- *Dual-variant determinations:* both variants are always computed. Reserve runs migration-analysis and static-pool and stores the one named by `reserve_method`; the lending measurement stores both dollar-weighted and count-weighted percentages and copies only `selected_pct` onto the institution.
- *Counter-intuitive orderings preserved verbatim:* underwriting checks the tier before `ERR_BORROWER_NOT_GEOCODED`; TA slot-conflict and measurement period-overlap are checked before their bounds validations.
- *Parallel state dimensions* are independent fields (`underwriting_state` × `servicing_state`, `certification_state` × `compliance_posture`), and the cascades bump each touched row's own `version`/`updated_at`: charge-off → reserve → PROBATION → award `DRAW_SUSPENDED` → commitment `HELD`; board resignation → accountability recompute → cert-app verdict + state.
- *OCC* is wired on exactly the two declared endpoints (`expected_institution_version` on cert-app create, `expected_loan_version` on impact-report filing) and is skipped when the field is absent.

**Verification.** All 18 modules pass `python3 -m py_compile`. Smoke boot on a free port (17685) from a fresh process: server answered, and a ~60-call end-to-end scenario (clock → institution → target market → board seat → certification docket through CERTIFIED → borrower/geocode → product → loan underwrite/approve/disburse → servicing run to DELINQUENT_90 → award + matching funds → measurement PASS → impact report verify, plus negative cases for duplicate EIN, SoD, match shortfall, pagination bounds, scope, 404, RBAC and unauthenticated) passed every status assertion and printed `SMOKE OK`. Hand-checked intermediate values matched: `accountability_score` 1.0, `income_pct_ami` 80.0, provisional payment 27500, `dti_pct` 19.38, tier B, reserve ratio 41.6667 → posture, goal attainment 33.33. Smoke server was shut down by its captured pid only (never a pattern kill) and the port confirmed free; `__pycache__` removed from the deliverable. The withheld `test_helpers/`, `test_suite/`, both design YAMLs and all sibling task directories were never opened.

## Step 5: Generate unit tests — 2026-09-04T09:20:00.000Z

ORCHESTRATOR DEVIATION, recorded for honesty: the skill mandates launching Steps 5 and 6
concurrently in a single assistant message, which gives the implementation generator *physical*
isolation from `test_suite/` (the directory does not exist when it boots). I launched Step 5 alone
first, so `test_suite/` and `test_helpers/` were already on disk when Step 6 started. Compensating
control applied instead: Step 6's prompt carried an ABSOLUTE PROHIBITION naming both directories
and forbidding read/list/glob/grep/reference of either. Step 6 reported on exit that
`test_helpers/`, `test_suite/`, both design YAMLs and all sibling tasks "were never opened".
The isolation was therefore instructional rather than physical for this task. Placement verified
by the orchestrator: both test dirs sit at the task root, nothing stray under `workspace/`.

Subagent summary (verbatim):

All three remaining files are written and the full verification sweep passes. Stage 1 + Stage 2 for task 2685 are complete.

## Files (line counts)

`test_helpers/` (Stage 1, 2,667 lines): `__init__.py` 37 · `api_errors.py` 134 · `types.py` 488 · `api_client.py` 452 · `constants.py` 101 · `test_users.py` 100 · `factories.py` 252 · `assertions.py` 232 · `fixtures.py` 873

`test_suite/` (Stage 2, 5,611 lines, 92 tests): `conftest.py` 72 · `test_01_dual_basis_determinations.py` 245 (4) · `test_02_pinned_formula_order.py` 200 (4) · `test_03_parallel_and_cyclic_lifecycles.py` 203 (4) · `test_04_transitive_cascades.py` 308 (4) · `test_05_rejection_precedence_pairs.py` 172 (4) · `test_06_threshold_and_pin_boundaries.py` 185 (4) · `test_07_cross_entity_gates.py` 257 (4) · `test_08_temporal_occupancy.py` 302 (4) · `test_09_compensating_reversals.py` 287 (4) · `test_10_entity_records.py` 466 (9) · `test_11_lifecycle_transitions.py` 382 (8) · `test_12_derived_figures.py` 250 (5) · `test_13_input_and_gate_validation.py` 646 (11) · `test_14_endpoint_round_trips.py` 368 (6) · `test_15_error_catalogue.py` 280 (3) · `test_16_role_boundaries.py` 444 (8) · `test_17_versioning_and_posture_layers.py` 433 (5) · `test_18_cross_aggregate_consistency.py` 109 (1)

Written this session: `test_16` (all 8 `rbac` instances — credit-role swap, officer/reviewer market split, cross-tenant officer scope, borrower impact scope, both loan and certification segregation-of-duties, unknown-role/empty-identity 401 ahead of every other band, shared geocoding with a third role refused), `test_17` (all 5 non-stub `cross_cutting_complexity_layers` — stale institution token with the version climbing per write, stale loan token ahead of supersession, posture walked at exactly 0.8000 and exactly 1.0000 then down to 0.4444/PROBATION, committed principal that counts approvals only, servicing-run recertification flip on the 1,095th day), `test_18` (the single `consistency_model` instance).

## Coverage

- **Queue A (Difficulty): 18/18** instances, 36 tests.
- **Queue B (Corner): 56/56** non-stub instances, 56 tests. The 17 `excluded_because:` stubs were not translated, per spec.
- **Skipped instances: none.**

## Verification

- Programmatic tag audit over all 28 emitted files: 92 tests, every docstring ends in exactly one `Design:` line, every tag resolves to a real `name:` in the two design yamls, every test carries at least one `PRD:` citation — zero problems.
- `find … -maxdepth 3 -type d -name 'test_*'` returns only the two task-root directories; nothing under `workspace/`, and nothing was read or written in `workspace/implementation/`.
- `ast.parse` over all 28 files: OK. `pyflakes` clean on every `test_suite/*.py` (the only warnings are the intentional re-exports in `test_helpers/__init__.py`). No file mentions "scaffold". Stray `__pycache__` removed.

## Three PRD-over-yaml judgement calls (instances kept, PRD-derived values asserted)

1. `validations/award_submit_needs_certification_first_then_a_commitment_and_then_succeeds` — the yaml expects a merely `PLEDGED` `CASH_PRIVATE` source to produce 1,000,000 eligible match; PRD lines 266/270 uniquely derive 0 eligible and a full 1,000,000 shortfall (only `VERIFIED` counts). Asserted the PRD figures; the instance's central claim (the two-rung submit gate) is untouched.
2. `cross_cutting_complexity_layers/stale_expected_institution_version_rejected_and_the_parent_version_climbs_per_write` — the yaml expects target-market approval *not* to bump the institution version; PRD line 165 states approval "advances the institution's `version` by 1", so the walk is asserted as 1 → 2 (approve) → 3 (seat) → 4 (accepted create), which is exactly the instance's own "version climbs per write" claim.
3. (Carried from earlier) `transitive_cascade/board_seat_resignation_cascade_reopens_certification_review` — `info_requested_reason` asserted as `ACCOUNTABILITY_TEST_FAILED` per PRD line 170, not the yaml's `ACCOUNTABILITY_LOST`.

Two smaller recipe corrections: the corner recipes' `00000000-0000-4000-8000-000000000000` is used as a local `UNKNOWN_ID` rather than the framework's all-zeros `NON_EXISTENT_UUID`, and the award `program` value `FINANCIAL_ASSISTANCE` (not in the PRD's declared set) was replaced with `CDFI_PROGRAM_FA`.

## Step 6: Generate implementation — 2026-09-04T09:45:00.000Z

Subagent summary (verbatim):

Implementation complete and verified.

## Deliverable
`/home/ubuntu/github/CodingPRD/tasks/task_2685_community_development_financial_institution_certification_lending/workspace/implementation/`

**Modules (18 .py files, 3187 lines) + `start.sh` (executable) + `requirements.txt` (`Flask==3.0.3`)**

Foundation: `app.py` 58 · `store.py` 149 · `errors.py` 83 · `numeric.py` 49 · `envelope.py` 104 · `auth.py` 84 · `shape.py` 194 · `calc.py` 249 · `services.py` 388
Routes: `routes/__init__.py` 0 · `institutions.py` 142 · `governance.py` 221 · `certification.py` 247 · `borrowers.py` 319 · `loans.py` 292 · `impact.py` 151 · `measurements.py` 159 · `awards.py` 298

**Endpoints: 71/71** (31 GET + 40 POST), matching the PRD §4 table row-for-row.

## Notable design decisions
- **Storage**: process-local dicts keyed by UUID in a single `Store`; empty on every boot; no seeding, no SQLite, no disk IO (grep-verified — the only `seed`/`preload` hits are comments asserting their absence). Required for `--isolation per-test-server`.
- **Logical clock**: all entity date fields read `store.now()`, default `2026-08-01T00:00:00Z`, moved only via `POST /cdfi/_clock/set_current_utc`; timestamps emit exactly 3 fractional digits.
- **Exact arithmetic**: `Fraction` → single `Decimal` `ROUND_HALF_UP` quantize; `float` never touches money or rates. Both opposite rounding orders kept: reserve sums exact products and rounds once; match rounds per commitment then sums.
- **Rejection precedence**: the 11-band ladder is positional in each handler. To keep band 2 ahead of band 3 for non-institution-addressed resources, handlers do a *non-fatal* lookup to derive the owning institution for `scope()`/`segregation()` and only then fall through to 404. `shape.body()` returns `{}` for a non-object payload rather than failing, so body parsing can't pre-empt a scope check.
- **Dual variants** always computed; the stored value is chosen by `reserve_method` / measurement basis.
- **Counter-intuitive orderings preserved**: underwriting tier before `ERR_BORROWER_NOT_GEOCODED`; TA slot conflict and measurement overlap before bounds.
- **Parallel state dimensions** tracked independently, and each cascade bumps every touched row's own `version`/`updated_at` (charge-off → reserve → PROBATION → award `DRAW_SUSPENDED` → commitment `HELD`; resignation → accountability → cert-app verdict + state).
- **OCC** on exactly the two declared endpoints; skipped when the field is absent.

## Smoke-boot result
All 18 modules pass `py_compile`. Fresh-process boot on free port 17685 answered, and a ~60-call end-to-end scenario passed **every** status assertion → `SMOKE OK`. It covered clock → institution → target market → board seat → full certification docket to CERTIFIED → borrower/geocode → product → loan underwrite/approve/disburse → servicing run to `DELINQUENT_90` → award + matching funds → measurement PASS → impact report verify, plus negatives for duplicate EIN (409), segregation of duties (403), match shortfall (422), pagination bounds (400), scope (403), 404, RBAC (403) and unauthenticated (401). Hand-checked values matched: `accountability_score` 1.0, `income_pct_ami` 80.0, provisional payment 27500, `dti_pct` 19.38, tier B, reserve ratio 41.6667, goal attainment 33.33.

Smoke server was shut down by its captured pid only (`kill 3774364`, no pattern kill), port confirmed free; `__pycache__` removed. `test_helpers/`, `test_suite/`, both design YAMLs and all sibling task directories were never opened.

## Step 7: Iterate tests + fixes — 2026-09-04 (diagnostic loop)

Three 8-round parallel stability sweeps (`--isolation per-test-server`, all rounds under `setsid`). Round 1: 72/92 in every round. Round 2: 91/92. Round 3: **92/92 in all 8 rounds.**

Fixes to `test_suite/` (assertions mis-translated PRD wording; no assertion weakened, no test deleted):
- 22 literals across `test_03`, `test_04`, `test_08`, `test_09`, `test_11`, `test_13`, `test_14`, `test_16`, `test_17`, `test_18`: server-stamped clock fields (`approved_at`, `resigned_at`, `closed_at`, `verified_at`, `decided_at`, `certified_at`, `recertification_due_at`, `finalized_at`) were asserted as `...T00:00:00Z`, the raw clock-input literal. PRD §2.2/§2.4 declare one output timestamp shape — "ISO 8601 UTC timestamp with three fractional digits" — so the expectation is `...T00:00:00.000Z`. Client-supplied echoes (`period_start`, `scheduled_start_at`, `committed_on`) were left verbatim, since PRD never asks them to be re-normalised.
- `test_17_versioning_and_posture_layers.py`: `loss_reserve_required_static_cents` expected 81,000 (= outstanding 1,800,000 x 4.5%). PRD §3.6 applies the vintage rate to *originally disbursed* principal and "the cohort never shrinks", i.e. 2,000,000 x 4.5% = 90,000. Corrected to 90,000.
- `test_13_input_and_gate_validation.py`: product override used `credit_building_features: ["REPORTS_TO_BUREAUS", "SECURED_SAVINGS"]`; `SECURED_SAVINGS` is not in the PRD's declared set, so the PRD-faithful implementation correctly answered `ERR_INVALID_REQUEST` and the whole test died in setup. Replaced with `SAVINGS_MATCH`.

Fixes to `workspace/implementation/`:
- `store.py`: added `fmt_date()` (calendar date only).
- `routes/loans.py` (`disburse`, `pay`): `first_disbursed_on` and `next_payment_due_on` now render as `YYYY-MM-DD`. PRD §3.6 stamps them from "the logical clock's **date**" / "that **date** advanced by 30 days"; they were being emitted as full timestamps. `parse_dt` already tolerates a bare date, so the measurement window filter and the days-past-due arithmetic are unaffected.
- `routes/institutions.py` (`servicing_run`): `days_past_due` is now recomputed and stored for *every* loan the run processes, not only for loans that move to a higher bucket. PRD §3.6 says the figure is "truncated toward zero and floored at 0" — a floor that is unreachable for a re-bucketed loan (always >= 30), so the recompute must reach loans left `CURRENT`. `touch()` is still called only when a field actually changed, so an untouched loan does not gain a version.

## Step 7: Run tests and iterate — 2026-09-04T10:05:00.000Z

Orchestrator verification (independent of the subagent's claim): all 8 `results.$i.json` files exist
under `workspace/implementation/` and each reports `passed=92 total=92 failed=0`. No implementation
`.py` file is newer than `results.1.json`, so the green sweep post-dates the final fix.

Subagent summary (verbatim):

All 8 parallel rounds are fully green: **92/92 passed in every round**, three iterations.

## Iterations

| Sweep | Result |
|---|---|
| 1 | 72/92 in all 8 rounds — 20 failing tests, identical set every round (no flakiness) |
| 2 | 91/92 in all 8 rounds — 1 failing test |
| 3 | **92/92 in all 8 rounds** |

## Tests deleted

None. Every failing assertion traced to a verbatim PRD sentence; all 20 were either a test-authoring slip or an implementation gap.

## Fixes to `test_suite/`

- **22 timestamp literals** across `test_03`, `test_04`, `test_08`, `test_09`, `test_11`, `test_13`, `test_14`, `test_16`, `test_17`, `test_18` — server-stamped clock fields (`approved_at`, `resigned_at`, `closed_at`, `verified_at`, `decided_at`, `certified_at`, `recertification_due_at`, `finalized_at`) were asserted as the raw clock-input literal `...T00:00:00Z`. PRD §2.2/§2.4 declare exactly one output timestamp shape — "ISO 8601 UTC timestamp with three fractional digits" — and no competing shape anywhere, so the faithful expectation is `...T00:00:00.000Z`. Client-supplied echoes (`period_start`, `scheduled_start_at`, `committed_on`) were deliberately left verbatim; PRD never asks those to be re-normalised, and the tests asserting them already pass.
- `test_17_versioning_and_posture_layers.py:...static_cents` — expected 81,000, which is outstanding principal (1,800,000) × 4.5%. PRD §3.6 applies the vintage rate to *originally disbursed* principal and states "the cohort never shrinks", i.e. 2,000,000 × 4.5% = **90,000**. Corrected.
- `test_13_input_and_gate_validation.py` — the product override passed `credit_building_features: ["REPORTS_TO_BUREAUS", "SECURED_SAVINGS"]`. `SECURED_SAVINGS` is not in PRD's declared set (`REPORTS_TO_BUREAUS`, `SAVINGS_MATCH`, `RATE_STEP_DOWN`, `DEFERRED_FIRST_PAYMENT`), so the implementation correctly answered `ERR_INVALID_REQUEST` and the test died in setup. Replaced with `SAVINGS_MATCH` (no PRD-required check was relaxed).

## Fixes to `workspace/implementation/`

- `store.py` — added `fmt_date()`, a calendar-date-only formatter.
- `routes/loans.py` (`disburse`, `pay`) — `first_disbursed_on` and `next_payment_due_on` now render as `YYYY-MM-DD`. PRD §3.6 stamps them from "the logical clock's **date**" and "that **date** advanced by 30 days"; they were emitted as full timestamps. `parse_dt` already tolerates a bare date, so the measurement-window filter (`routes/measurements.py`) and the days-past-due arithmetic (`routes/institutions.py`) are unaffected.
- `routes/institutions.py` (`servicing_run`) — `days_past_due` is now recomputed and stored for **every** loan the run processes, not only for loans promoted to a higher bucket. Decisive PRD evidence: the figure is "truncated toward zero and **floored at 0**", a floor that is unreachable for a re-bucketed loan (always ≥ 30 days), so the recompute must reach loans left `CURRENT`. `touch()` still fires only when a field actually changed, so an unchanged loan gains no `version`.

No test was skipped, xfailed, or downgraded to an HTTP-status assertion; no PRD-required implementation check was removed; storage remains in-memory only with no seeded data.

## Step 8: Finalize PRD — 2026-09-04T10:15:00.000Z

Orchestrator verification: `workspace/PRD_FINALIZED.md` exists at 415 lines vs `PRD.md` 413, and
`diff` confirms two real hunks (a §2.5 insert and a §3.6 revise) — not a byte-identical copy.

Subagent summary (verbatim):

Done. `PRD_FINALIZED.md` written with two targeted edits.

## Line counts
- `PRD.md`: 413 lines; `PRD_FINALIZED.md`: 415 lines — **+2 lines (+0.48%)**

## Changes
- **§2.5 (The Logical Clock)** — *insert* — new paragraph pinning output rendering of date/time fields: every server-derived instant stored on a resource (`approved_at`, `resigned_at`, `certified_at`, `recertification_due_at`, `decided_at`, `closed_at`, `verified_at`, `finalized_at`, plus `created_at`/`updated_at`) renders as ISO 8601 UTC with three fractional digits (`...T00:00:00.000Z`); `first_disbursed_on` and `next_payment_due_on` are calendar dates (`YYYY-MM-DD`); client-supplied instants/dates are echoed verbatim and never re-normalised — `implementation/store.py:42` (`fmt_dt`), `store.py:50` (`fmt_date`), `routes/loans.py:215,217,247`, `routes/governance.py:112,211`, `routes/certification.py:183,215,235,239,240`, `routes/borrowers.py:304`, `routes/impact.py:102`, `routes/measurements.py:139`, `services.py:282`.
- **§3.6 (servicing checkpoint)** — *revise* — replaced "Every loan the run re-buckets has its `days_past_due` stored." with: every loan the run *processes* stores its recomputed figure (bucket change or not), and storing an identical figure with no bucket move is not a mutation, so `updated_at`/`version` do not advance — `implementation/routes/institutions.py:123-137`.

## Per-edit pre-edit search log

**Edit 1 — §2.5 timestamp/date rendering**
- (a) Subject: the rendered shape of every stored datetime- or date-valued field.
- (b) Paths enumerated: grepped all of `implementation/` for `fmt_dt|fmt_date|date_floor|now()|parse_dt`, and separately for every `"*_at"`/`"*_on"` key plus `period_start|period_end|scheduled_*|committed_on|reporting_period_end`. Read `store.py` (`fmt_dt`, `fmt_date`, `date_floor`, `parse_dt`, `base_row`, `touch`), `shape.py:165-176` (`req_dt` returns the raw string *and* the parsed value), and every writer: `routes/governance.py` (approved_at, resigned_at), `routes/certification.py` (decided_at x3, certified_at, recertification_due_at), `routes/borrowers.py` (closed_at; scheduled_* stored raw), `routes/impact.py` (verified_at; reporting_period_end stored raw), `routes/measurements.py` (finalized_at; period_* stored raw), `routes/awards.py` (period_* and committed_on stored raw), `routes/loans.py:212-224,247` (first_disbursed_on, next_payment_due_on via `fmt_date`), `services.py:275-288` (`recertification_due_at` = client `period_end` + 1095d, formatted through `fmt_dt`). Also confirmed the two readers of the date-only fields tolerate a bare date: `calc.whole_days_past_due` via `parse_dt` in `routes/institutions.py:123` and the window filter in `routes/measurements.py:113`.
- (c) Adjustments made: (i) explicitly covered `recertification_due_at` "whether derived from the clock at certification or from a measurement's `period_end`", because the measurement path re-normalises a *client* value into the three-digit shape and a blanket "client values are echoed verbatim" rule would have contradicted `services.py:282`; (ii) scoped the verbatim-echo clause to an enumerated list of client-supplied fields rather than "all client input"; (iii) phrased the exception as the two named loan fields rather than "date fields", so `committed_on` (a client-supplied date echoed verbatim) is not swept into the `YYYY-MM-DD` rule.

**Edit 2 — §3.6 `days_past_due` storage scope**
- (a) Subject: which loans the servicing run writes `days_past_due` on, and the resulting version/`updated_at` bookkeeping.
- (b) Paths enumerated: `routes/institutions.py:112-146` (the run: skip set, `changed` flag computed before assignment, promotion-only bucket write, conditional `touch`), `calc.whole_days_past_due` and `calc.bucket_for`/`BUCKET_ORDER` (`calc.py:224-249`), and every other writer of `days_past_due`: `routes/loans.py:73` (creation, 0), `:250` (cure -> 0), `:258` (payoff -> 0) — none of which the new sentence describes. Also `store.touch` (`store.py:119`) and §2.4's "increments on every mutation" claim, to make sure "storing an identical figure is not a mutation" reads as a clarification of §2.4 rather than an exception to it.
- (c) Adjustments made: constrained the no-bump clause to the conjunction the code actually uses (figure identical **and** bucket assignment does not move `servicing_state`), since `changed` is also set by a promotion that occurs with an unchanged day count; and kept the claim local to the servicing run rather than generalising "unchanged cascades never bump `version`" across the system.

**No PRD edit** for the other three Step 7 items — all are pure test-side bugs against text the PRD already determines: the static-pool basis on originally disbursed principal with a non-shrinking cohort (§3.6, `calc.static_pool_reserve`), the four-member `credit_building_features` set (§3.4, `routes/borrowers.py` product publish), and the client-echoed `period_start`/`scheduled_start_at`/`committed_on` literals.

## Step 9: Complete PRD — 2026-09-04T11:10:00.000Z

ORCHESTRATOR DECISION (recorded per the autonomy instruction): Step 9 was run as **three
sequential file-partitioned passes** over a single shared `PRD_COMPLETED.md`, rather than one
monolithic scan. Rationale: the implementation is 3,198 lines across 18 modules and the PRD is
415 lines of very dense prose; a single subagent asked to scan all of it has, in prior runs of this
pipeline, produced a `PRD_COMPLETED.md` byte-identical to its input — i.e. the scan silently did
not happen. Partitioning bounds each pass's reading load and makes the "did it actually scan"
question checkable per pass. Partition:
  - Pass A — foundation/cross-cutting: app.py, auth.py, envelope.py, errors.py, numeric.py,
    shape.py, store.py, calc.py, services.py (1,365 lines)
  - Pass B — intake/governance routes: routes/institutions.py, governance.py, certification.py,
    borrowers.py (933 lines)
  - Pass C — lending/impact/award routes: routes/loans.py, impact.py, measurements.py, awards.py
    (900 lines), plus a closing §4/§5 table consistency sweep
Passes B and C were told the file already existed and to edit in place (never re-copy), and each was
told which conventions earlier passes had already pinned so they would not re-pin them.

Orchestrator verification: `PRD_COMPLETED.md` is 416 lines / 127,254 chars vs `PRD_FINALIZED.md`
415 lines / 103,667 chars — 53 diff hunks, NOT byte-identical, so all three scans really ran.
File ends at a real section boundary (final §5 error-table row). No `implementation/*.py` is newer
than `results.1.json`, so Steps 8-9 touched documentation only and the 8/8 green sweep still holds.

Aggregate across the three passes: 69 edits — 64 ambiguity-pins, 9 mismatch-revisions
(Pass A 25 = 23 pins + 2 mismatches; Pass B 20 = 17 + 3; Pass C 28 = 24 + 4).

### Pass A summary (verbatim)

PASS A complete. `workspace/PRD_COMPLETED.md` exists and carries 25 edited passages.

## Stats
- PRD_FINALIZED.md: 415 lines / 103,667 chars → PRD_COMPLETED.md: 416 lines / 116,754 chars (**+13,018 chars**, +1 line — one new bullet in §2.2; everything else is in-paragraph)
- **Ambiguity-pins: 23** · **Mismatch-revisions: 2** (§2.5 wall-clock claim, §3.6 static-pool "every older vintage")

## Changes
- §2.1 — revise — ambiguity — header emptiness: whitespace-only counts as empty; both headers stripped before role recognition and before any `X-User-ID` comparison — `auth.py:42-47`
- §2.1 — insert — ambiguity — institution-scope check runs only when the acting role is `InstitutionOfficer` on an officer-authorised endpoint, and is skipped when no owning institution resolves (missing resource / omitted body reference), letting the existence band report — `auth.py:60-67`
- §2.1 — insert — ambiguity — borrower-scope check likewise applies only to role `Borrower` and is skipped when the owning borrower is unresolvable — `auth.py:70-77`
- §2.1 — insert — ambiguity — each segregation check is skipped when the blocked identity can't be read (row absent, or `decided_by_user_id` still null on an undecided award) — `auth.py:80-84`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars (24 total), minted per response — `store.py:102-104`
- §2.2 — revise — **mismatch** — `api_request_timestamp` is the one host-clock read, never the logical clock — `envelope.py:16`
- §2.2 — insert — ambiguity — `message` wording not contractual; new bullet pinning the three transport rejections (unroutable 404, method 405, fault 500) all under `ERR_INVALID_REQUEST`, plus trailing-slash tolerance — `app.py:23,33-48`
- §2.3 — revise — ambiguity — non-integral `limit`/`offset` rejected; empty string = omitted; whitespace tolerated — `envelope.py:71-84`
- §2.3 — insert — ambiguity — `has_more` formula, offset-past-end yields empty page; `created_at` ties broken by insertion order, and that rule governs every ordered traversal — `envelope.py:48`, `store.py:126-131`
- §2.4 — revise — ambiguity — `id` is a v4 UUID; `created_at`/`updated_at` read the logical clock, so an unmoved clock leaves `updated_at` textually static while `version` advances — `store.py:98,107-123`
- §2.4 — insert — ambiguity — all twelve collections start empty, nothing seeded — `store.py:66-80`
- §2.5 — revise — **mismatch** — "Nothing reads the host's wall clock" narrowed to exclude `api_request_timestamp` — `envelope.py:16`
- §2.5 — insert — ambiguity — `to_iso8601` required, tolerant ISO grammar (Z / offset / no zone as UTC / bare date as midnight), unparseable → `ERR_INVALID_REQUEST`; response is empty `data`; clock may move backwards — `store.py:20-39`, `shape.py:165-170`, `routes/institutions.py:29-35`
- §2.5 — insert — ambiguity — client-supplied instants must parse under the same grammar; parsed instant drives all comparisons while the original text is stored/echoed — `shape.py:165-176`
- §2.6 — insert — ambiguity — client decimals are quantized round-half-up to declared places on receipt and the range is checked against the quantized value — `numeric.py:35-49`, `shape.py:89-110`
- §2.6 — insert — ambiguity — decimal fields serialise as plain JSON numbers, so trailing zeros are not preserved (`0.5`, `0.0`, `1.0`) — `store.py:144-153`
- §2.8 band 4 — insert — ambiguity — four conventions: JSON `null` ≡ absent; non-object/absent body ≡ no fields; strict type rules (bool never numeric, numeric strings rejected, integral floats accepted); body foreign keys deferred to the existence band (`institution_id`/`borrower_id`/`product_id` on loan filing, `borrower_id` on booking → 404 not 400), optional refs treat empty/wrong-type as unsupplied — `shape.py:13-33,59-66,189-194`
- §2.9 — insert — ambiguity — filters never reject: empty = absent, unknown value matches nothing, boolean filters accept `true/1/yes` / `false/0/no` case-insensitively and ignore anything else — `envelope.py:88-104`
- §2.11 — insert — ambiguity — posture bands are re-evaluated unconditionally, so posture moves both directions and skips bands (`PROBATION → WATCH` is reachable) — `services.py:192-196`
- §2.11 — insert — ambiguity — suspension fires on entry into `PROBATION`, not on residence — `services.py:197-198`
- §2.11 — insert — ambiguity — conditional touch: a cascade finding a derived figure unchanged writes nothing (coaching hours, committed principal, goal attainment, no-op checkpoint loan), with the institution as the deliberate exception (one bump per balance-moving op) — `services.py:132-134,156-158,254-256`, `routes/loans.py:226-227`
- §3.4 — insert — ambiguity — `ta_hours_total` recomputed from scratch over all `COMPLETED` sessions, borrower written only when it changes — `services.py:126-134`
- §3.5 step 2 — insert — ambiguity — capacity figures may be 0; zero income leaves DTI undefined and is reported as `ERR_UNDERWRITING_TIER_UNMET`, not a shape error or division by zero — `calc.py:85-86`, `routes/loans.py:113,130`
- §3.5 step 3 — insert — ambiguity — the tier walk is partitioned by score presence (scored never reaches E, scoreless never reaches A–D), and `ERR_UNDERWRITING_TIER_UNMET` is the single error for `allow_no_credit_score` false, sub-12.00 hours, and sub-`min_credit_score` — `calc.py:91-107`
- §3.5 — insert — ambiguity — TA prerequisite satisfied by any `COMPLETED`+verified session of the borrower, loan-attached or not, no hours minimum — `services.py:137-143`
- §3.5 — insert — ambiguity — `committed_principal_cents` re-derived as a full sum; product `version` advances only when it changes — `services.py:149-158`
- §3.6 — revise — **mismatch** — static-pool vintage rate: 3% for *every other* vintage, including one newer than the clock's year (reachable by moving the clock back) — `calc.py:144-146`
- §3.6 — insert — ambiguity — both portfolio figures re-derived as sums over all institution loans, not incremented — `services.py:164-174`
- §3.7 — insert — ambiguity — award row written only when `goal_attainment_pct` changes; `DRAFT`/`SUBMITTED`/`REJECTED` awards never touched — `services.py:247-256`
- §3.8 — insert — ambiguity — `dollar_weighted_pct` is 0.00 (not null/error) when `measured_principal_cents` is 0 — `calc.py:215-218`
- §3.8 — insert — ambiguity — `PASS` writes `recertification_due_at` regardless of `certification_state` (including `DECERTIFIED`), rendered per §2.5; `FAIL` outside `RECERT_DUE` changes nothing — `services.py:275-288`

## Per-module notes
- **app.py**, **auth.py**, **envelope.py**, **numeric.py**, **shape.py**, **store.py**, **calc.py**, **services.py** — all produced pins (listed above).
- **errors.py** — **nothing to pin.** Its only content is the `error_id → HTTP status` map, which matches PRD §5 entry-for-entry (all 50 ids, all statuses identical, including the non-obvious ones: `ERR_TA_PREREQUISITE_UNMET` 409, `ERR_UNDERWRITING_TIER_UNMET` 422, `ERR_POSTURE_NOT_COMPLIANT` 409, `ERR_MATCH_COMMITMENTS_UNVERIFIED` 409), plus the `ApiError` carrier and a message-derivation helper. The only unpinned behaviors were the message wording and the unknown-id fallback (unreachable, since every `fail()` call site uses a catalogued id); I pinned the former in §2.2 and left the latter alone rather than document dead code.

Route modules (`routes/*.py`) were deliberately left for passes B and C; my four small greps into them were read-only confirmations of cross-cutting helper semantics (`body_id` → existence band, `scope` before existence, unknown filter values, `req_dt` call sites) and I made no route-specific edits.

### Pass B summary (verbatim)

Pass B complete. All 20 edits applied in place with the Edit tool; no full rewrite, no new sections, line count unchanged.

**File size:** before 416 lines / 116,754 chars → after 416 lines / 120,350 chars (+3,596 chars).
**Counts:** 17 ambiguity-pins, 3 mismatch-revisions.

**Changes**

- §2.8 band 4 — insert — ambiguity — added the fifth conditionally-required case (`COMPLETED` close without `actual_hours`) and stated that the mirror-image prohibitions (tracts/ceiling supplied for the wrong market type, `target_market_id` named with the flag false) also report `ERR_INVALID_REQUEST` — borrowers.py:300, governance.py:38-44,153
- §2.9 — insert — ambiguity — nested owner-scoped lists honour the same filters as their flat counterpart minus the owner id — governance.py:66, certification.py:95, borrowers.py:92,191
- §2.9 — insert — ambiguity — on a flat list whose roles include `InstitutionOfficer`, the `institution_id` filter is the ownership-check subject; omitting it leaves the officer unscoped over all rows — governance.py:184-185, borrowers.py:271-273
- §3.1 — revise — ambiguity — `legal_name` non-empty; a malformed `ein` is band-4 `ERR_INVALID_REQUEST` while a duplicate is band-9 `ERR_DUPLICATE_EIN` — institutions.py:44-56
- §3.1 — revise — **mismatch** — dropped the "eleven-character" tract-code claim: codes are an array of strings of unchecked length; added `ami_threshold_pct` range (≥0, no ceiling, 2dp) and non-empty `name` — governance.py:32-34
- §3.1 — revise — ambiguity — the three approval guards run in order and each reports `ERR_INVALID_STATE_TRANSITION` — governance.py:104-110
- §3.1 — revise — ambiguity — both board-seat representation mismatches are `ERR_INVALID_REQUEST`; `target_market_id` is read twice (existence band for a non-empty string, shape band for empty/wrong type, absent = not supplied); `holder_name` non-empty — governance.py:144-154
- §3.2 — insert — ambiguity — opening a docket consults no institution `certification_state` and permits any number of concurrent dockets — certification.py:40-53
- §3.2 — revise — ambiguity — `evidence_note` accepted at any length and not persisted — certification.py:153
- §3.2 — revise — ambiguity — a re-recorded identical verdict still advances the application's `version` — certification.py:162-163
- §3.2 — revise — ambiguity — resubmit corrections are stored in either branch, denial included — certification.py:201-215
- §3.2 — revise — ambiguity — the resubmit denial branch keeps `info_requested_reason` and every verdict as they stand — certification.py:213-215
- §3.2 — revise — **mismatch** — the `CERTIFIED` outcome sets `certification_state` to `CERTIFIED` from any prior value (incl. `RECERT_DUE`/`DECERTIFIED`), not only `UNCERTIFIED → CERTIFIED` — certification.py:238
- §3.3 — revise — **mismatch** — `postal_code` is not five-digit-validated; `full_name`/`street_address`/`postal_code` are only required non-empty strings — borrowers.py:47-49
- §3.3 — revise — ambiguity — `UNMATCHED` ignores a supplied `census_tract_code` and leaves an earlier resolved tract standing on the row — borrowers.py:126-133
- §3.4 — revise — ambiguity — `credit_building_features` stored as supplied (order and repetition preserved); out-of-set member is `ERR_INVALID_REQUEST` — borrowers.py:154-155, shape.py:151-162
- §3.4 — revise — ambiguity — engagement `loan_id` need only resolve to some loan, checked against neither borrower nor institution — borrowers.py:223-225
- §3.4 — revise — ambiguity — `actual_hours` has no upper bound (the 8.00 ceiling binds only `planned_hours`); `competency_verified` defaults false — borrowers.py:298-299
- §3.4 — revise — ambiguity — `NO_SHOW` forces 0.00/false whatever the request supplied — borrowers.py:315-317
- §3.6 — insert — ambiguity — the servicing checkpoint's response body is the updated institution row — institutions.py:146

**Per-module coverage:** all four modules in my partition produced edits — institutions.py (2 own edits + role/filter conventions confirmed clean), governance.py (5), certification.py (6), borrowers.py (7). No module came back empty. Verified separately that every authorised-role list in §4 already matches the role tuples in my four modules (no edits needed), and that the clock setter, institution list filters, and the inert-institution field block in §3.1 ¶2 were already pinned exactly by Pass A.

### Pass C summary (verbatim)

Done. Summary below.

## File size
- Before: **416 lines / 120,350 chars** → After: **416 lines / 127,254 chars** (all edits are in-paragraph; no new sections, no new lines, table row counts unchanged: 71 endpoints + 52 errors).

## Counts
- **Ambiguity-pins (silence → pinned): 24**
- **Mismatch-revisions (PRD said something else): 4**

## Changes
- §2.1 — revise — mismatch — Borrower role description no longer claims it "may only read its own loans"; impl performs no borrower-ownership check on reads — `routes/loans.py:84-88`
- §2.1 — insert — mismatch — pinned that borrower-ownership is tested only on impact-report filing and correction, so a `Borrower` may read any loan and any report — `routes/impact.py:76-80`, `routes/loans.py:86`
- §2.1 — insert — mismatch — an `institution_id` naming the institution itself (path or body) is compared as written without being resolved, so a mismatched officer gets 403 even for a nonexistent institution — `routes/awards.py:44,90`, `routes/measurements.py:76`, `auth.py:55-67`
- §2.9 — insert — ambiguity — the impact-report flat list declares no `institution_id` filter, so officers page over every institution's reports unchecked — `routes/impact.py:83-92`
- §3.5 — revise — ambiguity — a `refinance_of_loan_id` resolving to another borrower's loan reports `ERR_LOAN_NOT_FOUND` in the existence band; nothing else about the prior loan is examined — `routes/loans.py:41-45`
- §3.5 — insert — ambiguity — complete initial null set on a new loan (capacity figures, whole pricing chain, both dates, `vintage_year`, audit anchors) with `borrower_in_target_market_at_origination` false rather than null — `routes/loans.py:47-79`
- §3.5 — insert — ambiguity — `credit_score_at_underwriting` carries no range constraint at all, unlike the borrower's `credit_score` — `routes/loans.py:115`
- §3.5 — insert — ambiguity — underwriting a loan not at `SCREENING` (including one already `UNDERWRITING`) is `ERR_INVALID_STATE_TRANSITION`, never `ERR_LOAN_NOT_IN_UNDERWRITING` — `routes/loans.py:116-117`
- §3.5 — insert — ambiguity — `approved_principal_cents` strictly positive when supplied, not capped by the request, and range-checked in the shape band even on a decline — `routes/loans.py:165`
- §3.5 — insert — ambiguity — `decline_reason` is optional and unconstrained; omitting it leaves null — `routes/loans.py:166,184`
- §3.6 — revise — mismatch — disbursement is declared for `underwriting_state` `APPROVED` **or** `CLOSED` and `servicing_state` `NOT_DISBURSED`/`CURRENT`/any delinquency bucket (PRD said "against an `APPROVED` loan"); `PAID_OFF`/`CHARGED_OFF`/pre-approval refused with `ERR_INVALID_STATE_TRANSITION`; `amount_cents` strictly positive — `routes/loans.py:20-22,202-208`
- §3.6 — insert — ambiguity — payment state guard (`CURRENT` + three buckets only), strictly positive amount, guard evaluated before the outstanding-balance ceiling — `routes/loans.py:23,237-241`
- §3.6 — insert — ambiguity — a partial payment on a delinquent loan moves only the balance: state, `days_past_due` and `next_payment_due_on` all untouched — `routes/loans.py:246-253`
- §3.6 — insert — ambiguity — `charge_off_reason` required non-empty yet not a declared `Loan` field and absent from the response — `routes/loans.py:271,280`, `store.py:134-141`
- §3.6 — insert — ambiguity — `reserve_deficit_cents` is written only by charge-off, overwritten (not accumulated) by a later one, and never recomputed or cleared by any other event — `routes/loans.py:285-290`, `services.py:176-198`
- §3.7 — insert — ambiguity — filing is not gated by the loan's own position; any `underwriting_state`/`servicing_state` accepted, including never-disbursed and charged-off — `routes/impact.py:29-44`
- §3.7 — insert — ambiguity — filing advances the institution's `updated_at`/`version` only when it superseded a `VERIFIED` report — `routes/impact.py:46-72`
- §3.7 — insert — ambiguity — `dispute_reason` required non-empty — `routes/impact.py:116`
- §3.7 — insert — ambiguity — all four counts required on a correction; the correction advances the report's `version` alone and touches neither loan nor institution — `routes/impact.py:141-150`
- §3.8 — insert — ambiguity — cutting a measurement writes nothing on the institution (no `target_market_lending_pct`, `certification_state` or `version` move) — `routes/measurements.py:43-62`
- §3.8 — insert — ambiguity — `first_disbursed_on` is read as midnight UTC of that calendar day when tested against the window's parsed instants — `routes/measurements.py:109-118`
- §3.8 — insert — ambiguity — `void_reason` required non-empty — `routes/measurements.py:153`
- §3.9 — insert — ambiguity — `awarded_amount_cents` optional non-negative (0 accepted), uncapped by the request, still range-checked on a rejection — `routes/awards.py:139,145-149`
- §3.9 — insert — ambiguity — `source_name` required non-empty; `committed_on` required, stored verbatim, never compared — `routes/awards.py:197-200,209`
- §3.9 — insert — ambiguity — a pledge against a `REJECTED` or `DRAW_SUSPENDED` award is `ERR_INVALID_STATE_TRANSITION`, and recording a pledge leaves the award row (ledger and `version`) untouched — `routes/awards.py:201-216`
- §3.9 — insert — ambiguity — `withdraw_reason` required non-empty; a `HELD` or `WITHDRAWN` commitment is refused with `ERR_INVALID_STATE_TRANSITION` — `routes/awards.py:287-289`
- §3.9 — insert — ambiguity — submission's declared-transition check (`DRAFT` only) precedes both the certification and match gates — `routes/awards.py:121-127`
- §3.9 — insert — ambiguity — resume-draws on any state other than `DRAW_SUSPENDED` is `ERR_INVALID_STATE_TRANSITION`, not `ERR_AWARD_NOT_AWARDED` — `routes/awards.py:178-179`

Per-module note: **all four modules** in my partition yielded pins — `loans.py` (10), `impact.py` (5, plus 2 of the §2.1/§2.9 pins), `measurements.py` (3), `awards.py` (6). None came up empty.

## Closing consistency sweep
- **§4 endpoint table:** programmatically diffed all 71 rows (method + path, `{id}` ↔ `<id>`) against every `@bp.get/@bp.post` in `routes/*.py` — **exact match in both directions, 71 = 71**, no extras or omissions. Authorised-role columns for the 28 rows belonging to my four modules were checked against each module's role tuples (`LOAN_READ_ROLES`, `LOAN_LIST_ROLES`, `FILE_ROLES`, `REPORT_READ_ROLES`, `REPORT_LIST_ROLES`, measurement `READ_ROLES`/`LIST_ROLES`, `AWARD_WRITE_ROLES`/`AWARD_READ_ROLES`/`AWARD_LIST_ROLES`, `COMMITMENT_READ_ROLES`) — **all consistent**. No table edits made.
- **§5 error catalogue:** 52 rows, identical id set and identical statuses to `errors.py:ERROR_STATUS` (52 entries), including the counter-intuitive ones my modules raise (`ERR_TA_PREREQUISITE_UNMET` 409, `ERR_UNDERWRITING_TIER_UNMET` 422, `ERR_POSTURE_NOT_COMPLIANT` 409, `ERR_MATCH_COMMITMENTS_UNVERIFIED` 409, `ERR_MATCH_SHORTFALL` 422, `ERR_FEDERAL_SOURCE_INELIGIBLE` 422). Every error id raised anywhere in `loans.py`, `impact.py`, `measurements.py`, `awards.py` appears in the table. **No mismatch found; tables left untouched.**

## Pipeline complete — 2026-09-04T11:12:00.000Z

Step 9 has written `workspace/PRD_COMPLETED.md`. All nine steps done.
