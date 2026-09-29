# Worklog — task_2663_qualified_domestic_relations_order_processing

## Step 1: Create task directory — 2026-09-04T03:26:00.000Z

Created `tasks/task_2663_qualified_domestic_relations_order_processing/` and `tasks/task_2663_qualified_domestic_relations_order_processing/workspace/`. Index 2663 was pre-assigned by the orchestrator invocation; no scan of ./tasks/ was performed.

## Step 2: Scaffold artifacts generated — 2026-09-04T05:10:00.000Z

Wrote all three scaffold files (incrementally, via heredoc appends):

- `SCAFFOLD.yaml` — §1.0–§1.7: 14 entities, 9 state machines, 2 §1.2.1 concurrency rules,
  15 calculations, 18 ordered validation rungs, 43 endpoints, 47 errors, 5 roles.
  Contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — §1.8, single top-level key: 9 rule ids / 24 instances
  (3,3,2,3,3,3,3,2,2).
- `SCAFFOLD_CORNER_DESIGN.yaml` — §1.9, single top-level key: 9 sections / 68 instances
  (38 with `test_recipe`, 30 `excluded_because` stubs citing §1.8 instances).

Audits run: `scaffold_lint.py` → `VERDICT: clean lint` (929 calls scanned); all 47 §1.6 error ids
triggered by some recipe; 72 inline "ERR_X … HTTP nnn" claims cross-checked against §1.6 (0
mismatches); instance names unique across §1.8 ∪ §1.9; no stub carries a `test_recipe` and every
citation resolves; all three files parse with `yaml.safe_load`.

Hard constraint honoured: no sibling task under `tasks/` was listed, globbed, grepped or read.

## Step 2 (orchestrator record): Generate Scaffold — 2026-09-04T05:11:00.000Z

Verbatim summary returned by the Step 2 subagent:

All three scaffold artifacts are complete and lint-clean.

## Files (all in `/home/ubuntu/github/CodingPRD/tasks/task_2663_qualified_domestic_relations_order_processing/`)

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 2534 | 147 KB |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2596 | 219 KB |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3500 | 261 KB |

All three parse with `yaml.safe_load`. `SCAFFOLD.yaml` top-level keys: `scenario, domain_name, api_prefix, response_envelope, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — neither design key present. The two design files each have exactly one top-level key.

## §1.0–§1.7 counts
14 entities (3 immutable: ValuationSnapshot, TaxReport, Communication) · 9 state machines (2 of them parallel dimensions on QdroCase) · 2 §1.2.1 concurrency rules · 15 calculations · 18 ordered validation rungs (priorities 10→70) · 43 endpoints · 47 errors · 5 roles (PlanAdministrator, QdroAnalyst opaque; Participant/AlternatePayee/Attorney entity-backed). Profile: `compliance_audit` + `ledger_reconciliation`, hybrid topology, branching machines, `segregation_of_duties` role model, `immediate` consistency, `expert_plus`.

## §1.8 — 9 rule ids / 24 instances
`dual_variant_calc` 3 · `combinatorial_formula` 3 · `non_linear_state_machine` 2 · `transitive_cascade` 3 · `priority_pair_validation_conflict` 3 · `boundary_precision_check` 3 · `cross_entity_state_dependency` 3 · `resource_temporal_overlap` 2 · `compensating_invariant` 2.

## §1.9 — 9 sections / 68 instances (38 active recipes + 30 `excluded_because` stubs)
entities 12 · state_machines 14 · calculations 13 · validations 10 · endpoints 6 · errors 3 · rbac 3 · cross_cutting_complexity_layers 6 (incl. both required `optimistic_concurrency` instances, one per §1.2.1 rule) · consistency_model 1.

## Verification
- `scaffold_lint.py` → **`VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`** (43 endpoints, 14 entities, 24 §1.8 + 38 §1.9 instances, 929 calls scanned)
- All 47 §1.6 error ids are triggered by some recipe; 72 inline "ERR_X … HTTP nnn" claims cross-checked against the catalog (0 mismatches).
- Instance names unique across §1.8 ∪ §1.9; every stub citation resolves to a real §1.8 instance; no stub carries a `test_recipe`; every active has `setup/setup_api_calls/trigger/assert`; every instance has `name/claim_type/grounds/distinguishing_aspect`.
- Hard constraint honoured: no sibling task directory was listed, globbed, grepped or read.

## Design adjudications made this session
1. **Unauthenticated rungs** are written as `as: NO_CREDENTIALS` with a `$.data.error_id` capture — the linter treats error-capturing calls as negative triggers and skips the role check, so the 401 rung is expressible without inventing a role.
2. **OCC literals are illegal even in negative calls**: an `expected_case_version: "1"` in the RBAC ownership test tripped lint rule (e); replaced with a captured `${c2_v}`, and the assert was rewritten to say a *fresh* version still yields `ERR_NOT_RESOURCE_OWNER` (priority 35 beats 44).
3. **Priority 55 outranks 62 and the notice window**: a draft that is both deficient and past its 548-day hold reports `ERR_SEGREGATION_WINDOW_EXPIRED`, and the notice's own open 60-day window does not rescue a resubmission.
4. **The void window is a calendar-year comparison**, not elapsed time — voidable at `2026-12-31T23:59:59Z`, refused one second later; the refused void appends nothing to the append-only ledger.
5. **Fee tier is keyed on net-after-withholding**, so a `DIRECT_ROLLOVER` of 300000 pays 5000 while a CASH gross of 100000 pays 2500 — used as the conditional-validation control alongside `ERR_ROLLOVER_INSTITUTION_REQUIRED`.
6. **`ERR_APPROACH_NOT_PERMITTED` is a compatibility pair** (asserted in both directions), not a plan-level allow-list check.
7. **The administrator is deliberately not a superset of the analyst** — the RBAC instance asserts symmetric `ERR_FORBIDDEN_ROLE` denials in both directions.
8. **Sweep semantics are skip-based, not transactional**: four successive sweeps show phase independence (an expired notice never denies its draft), per-row eligibility, and a pure no-op re-run.
9. Field-name/HTTP corrections applied: `admin_fee_cents` (not `administrative_fee_cents`), `tax_year` is an integer, `ERR_DRAFT_ORDER_NOT_UNDER_REVIEW`/`ERR_DRAFT_ORDER_NOT_DEFICIENT` (two invented ids removed), `GET /tax-reports` used instead of a non-existent case-scoped tax-report list, `POST /draft-orders/{id}/resubmit` re-roled to `Participant` (QdroAnalyst is not allowed there).
10. **Stubs were retro-fitted with `grounds` + `distinguishing_aspect`** — 16 state-machine/calculation stubs initially carried only `claim_type` + `excluded_because`, which violates the §1.9 instance schema.

## Step 3: Copy shared files — 2026-09-04T05:11:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2663_qualified_domestic_relations_order_processing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-04T05:35:00.000Z

ORCHESTRATOR NOTE — first attempt failed. The initial doc-generator subagent was terminated by an
infrastructure/API error after emitting only §1 through §3.6 (316 lines, no §4 endpoint reference and
no §5 error catalogue). Per the anti-truncation guard the truncated file was NOT hand-patched: it was
moved aside to `/tmp/PRD_2663_truncated_attempt1.md` and Step 4 was re-run from scratch in a fresh
subagent with explicit chunked-append discipline. Tail of the regenerated file verified by the
orchestrator: 468 lines, ends on the final row of the §5 error table (`ERR_ASSIGNED_AMOUNT_ZERO | 422`),
a real section boundary.

Verbatim summary returned by the (successful) Step 4 subagent:

PRD generated and audited: `workspace/PRD.md` — **468 lines**, complete, ending at a real boundary (final row of the §5 error table).

## Section list

| § | Title |
|---|---|
| 1 | Introduction (3 paragraphs) |
| 2 | Global Specifications & System-Wide Principles |
| 2.1 | User and Role-Based Access Control |
| 2.2 | API Response Structure *(verbatim from `section-2.2-response-structure.md`; diff shows only the trailing blank separator line)* |
| 2.3 | Pagination |
| 2.4 | Resource Identity, Timestamps and the Logical Clock |
| 2.5 | Money, Basis Points and Rounding Discipline |
| 2.6 | Path Resolution and Nested Resource Retrieval |
| 2.7 | Optimistic Concurrency on Case and Payee-Account Writes |
| 2.8 | Validation Precedence (all 18 rungs, in order) |
| 2.9 | Derived Balances and Ledger Reconciliation |
| 2.10 | Cascades, Versions and the Two State Dimensions of a Case |
| 2.11 | Disclosure Discipline and Attorney Interaction |
| 2.12 | Segregation of Duties |
| 3 | Business Logic & Workflows (9 subsections, chronological lifecycle) |
| 3.1 | Standing Up a Plan and Its Written QDRO Procedures |
| 3.2 | The Participant's Account Picture |
| 3.3 | Opening a Case, Authorizing Counsel, and Case Correspondence |
| 3.4 | Receipt of a Draft Order, Assignment Sizing, and Hold Placement |
| 3.5 | Pricing an Assignment Before It Is Committed |
| 3.6 | Deficiency Review, Rejection Notices, and the Resubmission Cycle |
| 3.7 | The Qualification Determination and the Segregation-to-Payee Cascade |
| 3.8 | Denial, Hold Release, and the Segregation Sweep |
| 3.9 | Alternate Payee Distributions, Tax Reporting, and Corrections |
| 4 | Endpoint Definitions (4 columns, 43 rows) |
| 5 | Error Code Catalogue (2 columns, 47 rows) |

## Coverage (scripted against SCAFFOLD.yaml, not eyeballed)

| Element | Scaffold | PRD-covered |
|---|---|---|
| Entities | 14 | 14 (all narrated; the 3 with `common_fields: false` explicitly called out as lacking `updated_at`/`version`) |
| Entity field names | 113 | 113 backticked (0 missing) |
| Endpoint input identifiers | 76 | 76 backticked (0 missing) |
| Computed-output identifiers (projection / sweep / clock) | 17 | 17 backticked |
| Endpoints | 43 | 43 rows matched exactly by `METHOD` + path |
| Error IDs | 47 | 47 (all present in §5 table **and** each triggered condition sited in §2/§3 prose) |
| Calculations | 15 | 15 (incl. all 3 with divergent variants: `earnings_growth_bps`, `benefit_assignment_projection`, `distribution_settlement`) |
| Validation rungs | 18 | 18, rendered as a numbered precedence ladder in §2.8 with the two deliberate orderings called out (window-before-revision-cap; state-before-OCC; disclosure-before-attorney-standing) |
| State machines / transitions | 9 / 37 | 9 / all transitions covered, including both sweep-driven `→ DENIED` branches and both `ESTABLISHED → CLOSED` routes |
| Concurrency rules | 2 | 2 (`expected_case_version` → `ERR_STALE_CASE_VERSION` 412; `expected_ap_account_version` → `ERR_STALE_AP_ACCOUNT_VERSION` 412) |
| Roles | 5 | 5, each with its `identity:` translated (2 opaque, 3 entity-backed) |
| State/enum literals | 23 states + 80 enum values | all present verbatim |

## Hard-contract reports

```
Field coverage check:
- entities[].fields: 113 required, 113 present, 0 missing
- endpoints[].input: 76 required, 76 present, 0 missing
- computed output identifiers: 17 required, 17 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 18 checked, 18 expressed as an ordered ladder, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + occ_field + error_id + 412), 0 missing
- state_machines[].transitions: 37 checked, 37 fully expressed, 0 missing
- calculations[]: 15 checked, 15 fully expressed (pinned rounding orders + worked divergences retained), 0 missing
- validations[] conditions: 18 checked, 18 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 20 checked, 20 expressed, 0 missing
- entities[].fields[] structured content: 113 checked, 113 reconstructible (types, defaults, ranges, initial values), 0 missing
- sibling-branch symmetry: 6 groups checked (SEPARATE_INTEREST/SHARED_PAYMENT at L3/L4/L5/L6, PERIOD_END/PRO_RATA_DAILY, CASH/DIRECT_ROLLOVER), equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 780
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- unbacktick'd raw paths in §3: 0
Status: PASS
```

Exact tail line: `| `ERR_ASSIGNED_AMOUNT_ZERO` | 422 |`

Note per instruction: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was read. All worked examples in the PRD (the 548-day expiry boundary, the 48001-vs-48000 earnings divergence, the 1050000-cent fee-tier flip, the 1100000-cent capacity refusal) come from `SCAFFOLD.yaml`'s own `precision`/`notes` fields.

## Stage 2 complete — test_suite/ finished (16 files, 86 tests)

Final three files: test_14 (attorney standing / disclosure scope, 5 tests),
test_15 (role matrix and row ownership, 2 tests), test_16 (optimistic concurrency
and custody conservation, 4 tests). Added `read_authorizations` to
test_helpers/fixtures.py as the list channel for attorney authorizations.

Coverage audit: all 24 difficulty instances carry >= 2 tests; all 38 non-stub
corner instances carry >= 1 test; the 30 `excluded_because` corner stubs emit
nothing. Every test carries exactly one `Design:` line and one grep-verified
contiguous PRD quote. compileall + pyflakes clean; `pytest --collect-only -q`
collects 86 tests with no errors.

## Step 5: Generate Unit Tests — 2026-09-04T07:32:00.000Z

Verbatim summary returned by the Step 5 subagent:

Stage 1 and Stage 2 are complete. Everything lives directly under the task root; nothing was written under `workspace/`, and `workspace/implementation/` was never read or touched.

## Files written

`test_helpers/` (9 modules): `__init__.py` 40, `types.py` 290, `constants.py` 142, `api_errors.py` 144, `test_users.py` 116, `api_client.py` 247, `assertions.py` 478, `factories.py` 205, `fixtures.py` 455 (grew by `read_authorizations`, the list channel for attorney authorizations).

`test_suite/` — `conftest.py` 37 plus 16 test modules / 86 tests:

| file | lines | tests |
|---|---|---|
| test_01_plan_and_account_setup | 507 | 7 |
| test_02_identifier_resolution_and_input_validation | 438 | 5 |
| test_03_status_lifecycles | 731 | 6 |
| test_04_assignment_base_and_deficiency_evaluation | 742 | 6 |
| test_05_earnings_and_formula_pricing | 750 | 8 |
| test_06_validation_ladder_and_conditional_rules | 741 | 5 |
| test_07_rung_precedence_and_marital_exclusivity | 783 | 6 |
| test_08_review_cycle_and_case_dimensions | 598 | 6 |
| test_09_qualification_cascade_and_error_contract | 564 | 6 |
| test_10_segregation_lapse_and_expiry_boundary | 585 | 5 |
| test_11_release_gate_and_aggregate_capacity | 466 | 4 |
| test_12_distribution_settlement_and_withholding | 473 | 6 |
| test_13_void_compensation_and_tax_ledger | 360 | 4 |
| test_14_attorney_standing_and_disclosure_scope | 700 | 5 |
| test_15_role_matrix_and_row_ownership | 345 | 2 |
| test_16_optimistic_concurrency_and_custody_conservation | 559 | 4 |

## Instance translation tally

- **Queue A (§1.8 difficulty): 24 of 24 instances translated**, every one with ≥2 tests. 0 skipped.
- **Queue B (§1.9 corner): 38 of 38 non-stub instances translated**, every one with ≥1 test. The 30 instances carrying `excluded_because` emitted nothing, as required. 0 non-stub skips.

No instance was skipped, but individual assertions were dropped where the PRD does not uniquely derive them (gaps left as gaps, no weakening or xfail): the sweep report's `evaluated_count` (never asserted anywhere), `created_at == updated_at` on creation (ISO-8601 shape only), identity-scoped list results for entity-backed roles (`GET /draft-orders` as a participant — the PRD pins no such scoping), and the `COVERTURE_FRACTION` / null-`marital_period_end` step whose `CODE_MARITAL_PERIOD_UNDEFINED` has no PRD rule. Three recipe literals were corrected against the PRD rather than copied: `template_code` `QUALIFICATION_NOTICE` and `STATUS_UPDATE` (not in the PRD enum → `DETERMINATION_QUALIFIED`), the corner sweep's hold-Y expiry (recipe `2028-04-02`, hand-counted `2028-04-01`), and the segregation-window recipe's `ERR_SEGREGATION_WINDOW_EXPIRED` claim (rung 9 precedes rung 13, so the test uses two participants).

## Audit results

- `python3 -m compileall -q test_helpers test_suite` → clean (COMPILE_OK).
- `python3 -m pyflakes test_helpers/*.py test_suite/*.py` → clean, no unused imports or undefined names.
- `python3 -m pytest test_suite --collect-only -q` → **86 tests collected, 0 errors**.
- Tag/quote verifier (AST walk of every test): **86 tests checked, 0 problems** — exactly one `Design:` line per test, every tag resolving to a real `name:` in the correct yaml, and every first `PRD: "…"` block a verbatim contiguous substring of `workspace/PRD.md`.
- `__pycache__`/`.pytest_cache` artifacts removed; both output directories contain only source.

## Step 6: Generate Implementation — 2026-09-04T07:32:30.000Z

Verbatim summary returned by the Step 6 subagent:

Implementation complete and verified.

## Files written — `workspace/implementation/`

| file | lines | role |
|---|---|---|
| `timeutil.py` | 90 | ISO-8601 parse/format (3 fractional digits), whole-day/half-open-day arithmetic, 59.5-year calendar math |
| `errors.py` | 123 | `ApiError` + all 47 error-id constants + `HTTP_STATUS` map |
| `envelope.py` | 87 | PRD §2.2 envelope, `req_` + 20 alnum ids, pagination bounds (§2.3) |
| `store.py` | 121 | in-memory dicts for all 14 entity types, logical clock (default `2026-08-01T00:00:00Z`), `_seq` tie-breaker, `public()` key stripping |
| `validation.py` | 201 | rung 3 shape checks (all → `ERR_INVALID_REQUEST`) |
| `enums.py` | 79 | every declared literal set + plan procedure transitions |
| `auth.py` | 137 | rungs 1/2/6/7 (`endpoint()` decorator, ownership, attorney standing) |
| `calc.py` | 205 | deficiency evaluation, coverture, sizing + ceilings, allocation waterfall, earnings, basis carryover, shared-payment slice, 7-step distribution settlement |
| `services.py` | 366 | lookups, derived-balance recomputation, correspondence pairs, tax ledger, capacity check, 3-phase sweep |
| `routes_plans.py` | 100 | 4 endpoints |
| `routes_participants.py` | 178 | 9 endpoints |
| `routes_cases.py` | 256 | 10 endpoints |
| `routes_drafts.py` | 438 | 8 endpoints (receipt/supersede, notices, resubmit, 7-level qualification cascade, denial) |
| `routes_holds.py` | 74 | 3 endpoints |
| `routes_payees.py` | 214 | 7 endpoints (distribution, void, tax reports) |
| `routes_ops.py` | 26 | 2 endpoints (clock, sweep) |
| `app.py` | 66 | blueprint registration, `ApiError`/404/405/500 handlers, binds `0.0.0.0:$PORT` (default 10000) |
| `start.sh` | 9 | guarded `pip install flask`, `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0` |

Total 2771 lines. Storage is in-memory only; a fresh boot starts with every collection empty (verified: the plan-participants list returned `total_count: 0` on a clean process) and nothing is seeded anywhere.

## Checks
- **Endpoints: 43/43.** Dumped `app.url_map` and diffed against the PRD §4 table — exact match on method, path *and* authorized-role set for every row (including the `_clock`/`_ops` capabilities).
- **Error ids: 47/47.** Programmatically extracted the PRD §5 catalogue and compared to `errors.HTTP_STATUS`: no missing ids, no extras, **no HTTP-status mismatches**. Every id is also textually referenced from a non-`errors.py` module (0 unreferenced).
- `python3 -m compileall -q .` clean.

## Smoke evidence (real boots on private ports 18763 / 18771, killed with `fuser -k <port>/tcp` only)
```
POST /plans                 → 201 {"data":{...,"procedures_status":"DRAFT","version":1},"response_type":"object"}
GET  /plans/{id}            → 200 same envelope, meta.api_request_id "req_COSVQ7YZOQ6S602GSAFG"
POST /plans {"plan_name":""} → 400 {"error_id":"ERR_INVALID_REQUEST","message":"Field 'plan_name' must be 1..120 characters."}
GET  /plans/{id}/participants → 200 {"data":[],"meta":{...,"limit":10,"offset":0,"total_count":0,"has_more":false},"response_type":"array"}
```
Two full end-to-end passes exercised all 43 routes. Highlights confirming the pinned arithmetic and cascades:
- separate-interest qualification: hold `HELD→CONVERTED` (`segregation_date` stamped), AP account `balance 480000 / basis 72000` (per-source basis rounded down, last source absorbing residue), plan account `vested 1650000→1170000`, `held_amount 0`.
- cash distribution of 100000: `basis_recovery 15000 / taxable 85000 / withheld 17000 / net_before_fee 83000 / fee 2500 / net 80500 / CODE_2`; void → 2 ledger rows (second with `correction_of_tax_report_id` set, negated figures), AP totals back to 0.
- shared-payment qualification: hold `HELD→RELEASED`, `per_period_amount_cents 128000` (matches the PRD/scaffold worked example), `DIRECT_ROLLOVER` of 128000 → `withheld 0 / fee 5000 / CODE_G`, participant sources debited (`assignable_base 1000000→872000`).
- ladder spot-checks: `401 ERR_UNAUTHENTICATED`, `403 ERR_FORBIDDEN_ROLE`, `403 ERR_SEGREGATION_OF_DUTIES`, `403 ERR_ATTORNEY_NOT_AUTHORIZED` after revoke, `404 ERR_PLAN_NOT_FOUND`, `409 ERR_DENIAL_NOT_PERMITTED` (system-only `SEGREGATION_LAPSED` refused), `409 ERR_QUALIFICATION_DEFICIENCIES_PRESENT`, `412 ERR_STALE_CASE_VERSION`, `422 ERR_VALUATION_SNAPSHOT_MISSING`, `400` on `limit=0`.
- sweep idempotence: first run `evaluated_count 1` with the expired hold, lapsed case and system-denied draft listed; immediate second run at the same clock returned all-empty lists and `evaluated_count 0`.

Ambiguities resolved (documented choices): shape (400) is validated before path existence per §2.8/scaffold priorities; SoD (rung 8) precedes the draft-state check (rung 9) per §2.8 over §3.7 prose; `proposed_percentage_bps`/`proposed_flat_amount_cents` take the field-specific minimum of 1 (400), leaving `ERR_ASSIGNED_AMOUNT_ZERO` for empty bases/ceilings/coverture-rounds-to-zero; the segregation window is enforced on notice issuance per §3.6; money-source basis is not debited at qualification or distribution (only balances), per scaffold L5/void wording.

I did not read, list or open `test_helpers/`, `test_suite/`, either `SCAFFOLD_*_DESIGN.yaml`, or any sibling task directory, and no broad pattern kill was ever run.

## Step 8 — test/fix iteration loop (diagnostic expert)

Two iterations. Final state: 8/8 parallel rounds green at 86/86 (no tests deleted).

Iteration 1 (49/86 in all 8 rounds, 37 failures, fully deterministic — no flakiness):
- `implementation/timeutil.py` + `store.py` + `routes_drafts.py` — added `fmt_domain_instant`
  and routed every logical-clock domain stamp (`received_at`, `review_deadline_at`,
  `placed_at`, `expires_at`, `issued_at`, `resubmission_deadline_at`, `revoked_at`,
  `sent_at`, `established_at`, `voided_at`, `written_at`) through it, so they render at
  the clock's own precision as PRD 2.4 ("reads exactly 2026-08-01T00:00:00Z") and PRD 3.4
  ("A hold placed at 2026-09-01T00:00:00Z ... expires at 2028-03-02T00:00:00Z") render
  them. `created_at`/`updated_at`/`api_request_timestamp` keep three fractional digits
  via the new `Store.row_stamp()`, which is the only precision PRD 2.4 actually pins.
- `implementation/calc.py` + `routes_drafts.py` (qualify, Level 5) — split
  `basis_carryover` into `per_source_basis` and debit each converted source's
  `basis_cents` by its own contribution. PRD 3.5 "After-tax basis follows the principal
  it belongs to" plus PRD 3.7 Level 5 naming `after_tax_basis_cents` among the figures
  the debit forces the account to recompute.
- `test_suite/test_14_...py` `_two_cases_each_with_counsel` — re-read both cases before
  returning them; PRD 3.3 "recording one increments the case's version by one" made the
  intake-time rows stale, so the later receipt tripped ERR_STALE_CASE_VERSION in setup.

Iteration 2 (84/86 in all 8 rounds, 2 failures):
- `test_suite/test_08_...py` `test_republishing_...` — plan version 4 -> 6; the assertion
  omitted PRD 3.2's "Enrolling a participant ... increments the plan's version by one"
  for the scenario's two enrolments.
- `test_suite/test_14_...py` `test_the_scope_objection_outranks_the_missing_standing` —
  case version 2 -> 4; the assertion omitted PRD 3.3's two authorization-recording
  increments. The point the test makes (revocation and the refused letter touch nothing)
  is preserved.

## Step 7 (orchestrator record): Run Tests and Iterate — 2026-09-04T08:20:00.000Z

Orchestrator verification of the final sweep (independent of the subagent's claim): all 8
`workspace/implementation/results.{1..8}.json` exist, each reporting `passed=86 failed=0 errors=0 total=86`.

Verbatim summary returned by the Step 7 subagent:

No skips or xfails; all 86 tests intact and passing in every round.

## Summary

**Iterations run:** 2 (each an 8-round parallel `setsid nohup` sweep). Final sweep: **86/86 passing in all 8 rounds**, `failed=0 errors=0`. Failures were fully deterministic (identical set in all 8 rounds both times) — no flakiness or load-induced noise.

**Tests deleted:** none. Every failing assertion traced to a verbatim PRD sentence and was uniquely derivable.

**Fixes applied to `implementation/`:**
- `workspace/implementation/timeutil.py` — added `fmt_domain_instant()`: renders a logical-clock instant without a fractional part when the microsecond is 0. PRD 2.4 pins "three fractional digits" only for `created_at` / `api_request_timestamp`, and says the unset clock "reads **exactly** `2026-08-01T00:00:00Z`"; PRD 3.4 pins "A hold placed at 2026-09-01T00:00:00Z … expires at 2028-03-02T00:00:00Z".
- `workspace/implementation/store.py` — `Store.now_iso()` now uses `fmt_domain_instant`; new `Store.row_stamp()` keeps `created_at`/`updated_at` at three fractional digits. This moved all 12 clock-derived stamps (`received_at`, `placed_at`, `issued_at`, `sent_at`, `established_at`, `revoked_at`, `voided_at`, `written_at`, …) onto the PRD's rendering. ~31 of the 37 iteration-1 failures were this single root cause.
- `workspace/implementation/routes_drafts.py` — the three deadline computations (`review_deadline_at`, hold `expires_at`, `resubmission_deadline_at`) switched from `fmt_instant` to `fmt_domain_instant`.
- `workspace/implementation/calc.py` — split `basis_carryover` into `per_source_basis` (per-source, rounded down) + a sum.
- `workspace/implementation/routes_drafts.py` (`qualify_draft_order`, cascade Level 5) — each converted assignable money source's `basis_cents` is now debited by its own basis contribution, not just its `balance_cents`. PRD 3.5 "After-tax basis follows the principal it belongs to", and PRD 3.7 Level 5 lists `after_tax_basis_cents` among the figures this debit forces the account to recompute — which is a no-op unless `basis_cents` moves.

**Fixes applied to `test_suite/`** (no `test_helpers/` changes were needed):
- `test_14_attorney_standing_and_disclosure_scope.py` `_two_cases_each_with_counsel` — re-read both case rows before returning. PRD 3.3: "recording one increments the case's `version` by one", so the intake-time rows were stale and the later receipt correctly tripped `ERR_STALE_CASE_VERSION` in setup.
- `test_08_review_cycle_and_case_dimensions.py` `test_republishing_makes_the_identical_request_succeed_untouched` — expected plan `version` 4 → 6; the assertion omitted PRD 3.2's "Enrolling a participant … increments the plan's `version` by one" for the scenario's two enrolments.
- `test_14_...py` `test_the_scope_objection_outranks_the_missing_standing` — expected case `version` 2 → 4; the assertion omitted PRD 3.3's two authorization-recording increments. The behaviour the test actually targets (revocation and the refused letter disturb nothing) is preserved, since PRD 3.3 gives revocation only the authorization's own version bump.

## Step 8: Finalize PRD — 2026-09-04T08:34:00.000Z

Not skipped: Step 7 applied 5 `implementation/` fixes, so PRD-silence sites existed. Orchestrator
verification: `PRD.md` 468 lines, `PRD_FINALIZED.md` 470 lines, files differ, tail still ends on
`| ERR_ASSIGNED_AMOUNT_ZERO | 422 |`.

Verbatim summary returned by the Step 8 subagent:

Both edits are in place. Verification complete.

## Result

`PRD.md` 468 lines → `PRD_FINALIZED.md` 470 lines (**+2 lines, +0.43%**). Tail is byte-identical; the document still ends at §5's error catalogue table (`ERR_ASSIGNED_AMOUNT_ZERO | 422`).

Only **2** of the `<step_7_diff>` items required a PRD patch. The three `test_suite/` fixes and the `calc.py` refactor needed none — see the "no-edit" rationale below.

### Changes

- **§2.4 (Resource Identity, Timestamps and the Logical Clock) — insert — one new paragraph pinning how clock-derived domain instants render: no fractional part when the clock's microsecond is 0, three digits otherwise; `created_at`/`updated_at`/`api_request_timestamp` always three digits; clock-set response echoes `current_utc` verbatim.** — `implementation/timeutil.py:62-77` (`fmt_domain_instant`), `store.py:49-55` (`now_iso` / `row_stamp`), `routes_drafts.py:130,144,244,298`, `routes_ops.py:18-20`.
- **§3.7 Level 5 — revise — each assignable money source's `basis_cents` is also debited (by that source's own basis-carryover contribution, computed pre-debit), not just `balance_cents`; recompute trigger widened to "balances and bases".** — `implementation/routes_drafts.py:381-390`, `calc.py:142-156` (`per_source_basis`).

### Per-edit pre-edit search log

**Edit 1 — §2.4 timestamp rendering**
- (a) Subject: the rendering of every ISO 8601 instant this API emits, and which of them read the logical clock.
- (b) Paths enumerated: `grep -rn "now_iso\|row_stamp\|fmt_domain_instant\|fmt_instant"` over all of `implementation/` → the complete closed set of 12 clock-derived stamps (`routes_drafts.py:127,130,143,144,243,244,298,368`; `routes_cases.py:177`; `routes_payees.py:96,164`; `services.py:153,259`); `store.py:78,88` (`created_at`/`updated_at` via `row_stamp` → always 3 digits); `envelope.py:24` (`api_request_timestamp` via wall clock → 3 digits); `routes_ops.py:15-20` (clock endpoint echoes `data["current_utc"].strip()` and `db.clock_raw`, i.e. **not** reformatted); `routes_cases.py:144` (an `AttorneyAuthorization`'s **client-supplied** `expires_at` stored as the raw request string); `timeutil.py:88-90` (`add_days` preserves the microsecond, so deadlines inherit the clock's precision); `routes_drafts.py:376` / `timeutil.py:80` (`segregation_date` is a calendar date, not an instant).
- (c) Adjustments made: (i) wrote the field list as a **closed "namely" enumeration** rather than a universal rule about instant-valued fields, so the authorization's raw-echoed `expires_at` and the calendar-date `segregation_date` are not swept in; (ii) added the explicit `created_at`/`updated_at`/`api_request_timestamp` carve-out so the new rule cannot be read as overriding the existing three-digit sentence; (iii) added the whole-day-arithmetic clause because `review_deadline_at`, hold `expires_at` and `resubmission_deadline_at` are clock **plus days**, not the clock itself; (iv) rewrote a first draft that said the clock response reports both values "as the strings they were supplied as" — `previous_utc` on a never-set clock is the literal default and was never supplied — into "echoes the supplied `current_utc` verbatim and reports as `previous_utc` the string the clock previously read", which holds on both branches.

**Edit 2 — §3.7 Level 5 basis debit**
- (a) Subject: every write to a `MoneySource`'s `basis_cents`, and every place a source debit occurs.
- (b) Paths enumerated: `routes_drafts.py:387-390` (the Step 7 site — separate-interest qualification debits both `balance_cents` and `basis_cents`); `routes_drafts.py:392-397` (shared-payment branch — **no** source touched at all); `routes_payees.py:109-113` (shared-payment distribution issuance debits `balance_cents` **only**, leaving `basis_cents` intact); `routes_payees.py:167-175` (void credits back `balance_cents` **only**); `routes_participants.py`/money-source creation (initial `basis_cents`); `services.py:108-127` (`recompute_plan_account` — `after_tax_basis_cents` = sum of `basis_cents` over assignable sources, so the L5 debit is what makes that figure move); `calc.py:142-156` (`per_source_basis` skips zero-balance sources and rounds down per source — already exactly what §3.5 states).
- (c) Adjustments made: kept the sentence **inside** the existing "but only in the separate-interest shape" scope and did not lift it into a general "a debited source's basis moves with it" rule — that would have contradicted `routes_payees.py:111` and `:173`, where shared-payment issuance and void move `balance_cents` alone. Also added "computed from the balance and basis the source carried before the debit" to pin the ordering, and delegated the per-source arithmetic to §3.5 by reference rather than restating it, so the zero-balance-skip and round-down-per-source rules stay in one place.

### Items deliberately not patched
- **`test_14` `_two_cases_each_with_counsel` stale case rows**, **`test_08` plan `version` 4→6**, **`test_14` case `version` 2→4** — all three trace to increments PRD already states verbatim (§3.3 "recording one increments the case's `version` by one"; §3.2 "Enrolling a participant … increments the plan's `version` by one"). Pure fixture/assertion bugs; PRD prose left untouched.
- **`calc.basis_carryover` split into `per_source_basis` + a sum** — a refactor with no observable behavioural change on its own; §3.5 already defines the carryover per source and then sums. It is the *consumer* of that split (Edit 2) that needed pinning.

## Step 9: Complete PRD — 2026-09-04T10:00:00.000Z

ORCHESTRATOR DECISION: Step 9 was executed as THREE SEQUENTIAL FILE-PARTITIONED PASSES rather than a
single subagent. Rationale: the implementation is 17 modules / ~2800 lines, and a single-pass full scan of
an implementation this size reliably under-scans (the tell being a PRD_COMPLETED.md byte-identical or
near-identical to its source). Partitioning bounds each pass's reading load while keeping the scan
exhaustive. Pass 1 created PRD_COMPLETED.md from PRD_FINALIZED.md and audited the cross-cutting core
(app/timeutil/errors/envelope/store/validation/enums/auth/calc/services); pass 2 audited
routes_plans/routes_participants/routes_cases; pass 3 audited
routes_drafts/routes_holds/routes_payees/routes_ops and, as the final pass, was given standing authority
to correct any claim an earlier pass had inserted that its own partition contradicted (it used that
authority twice on its own inserts). Each pass edited the same file in place with the Edit tool.

Orchestrator verification of the final artifact: PRD_FINALIZED.md 470 lines / 100,988 chars →
PRD_COMPLETED.md 470 lines / 116,344 chars; files differ (`cmp`); heading count 29 and table-row count 94
identical in both, so no markdown structure was broken; last line is `| ERR_ASSIGNED_AMOUNT_ZERO | 422 |`.
Total across the three passes: 50 in-paragraph edits (39 ambiguity-pins, 11 mismatch-revisions), no new
sections and no new paragraphs. No implementation file is newer than results.1.json, confirming the
8-round 86/86 sweep from Step 7 still describes the shipped implementation.

Verbatim summary returned by Step 9 PASS 1 (core modules):

Pass 1 complete. `PRD_COMPLETED.md` created from `PRD_FINALIZED.md` and patched in place.

## Line counts / delta
- `workspace/PRD_FINALIZED.md`: 470 lines, 100,988 chars
- `workspace/PRD_COMPLETED.md`: 470 lines, 108,728 chars (**+7,740 chars**)
- 20 lines changed, all in-paragraph inserts/revisions. No new sections, no new paragraphs, no table rows.
- Confirmed final line is `` | `ERR_ASSIGNED_AMOUNT_ZERO` | 422 | ``.

## Counts
- ambiguity-pins: **17**
- mismatch-revisions: **3**

## Changes
- §1 (intro, time paragraph) — revise — mismatch — "nothing in this API consults wall-clock time" was a false universal; narrowed to domain fields/decisions with `api_request_timestamp` named as the one exception — `envelope.py:24`, `timeutil.py:84`
- §2.1 ¶1 — insert — ambiguity — an empty (not just absent) `X-User-ID`/`X-User-Role` is also 401 — `auth.py:43`
- §2.1 last ¶ — insert — ambiguity — an Attorney `X-User-ID` naming no authorization at all fails ownership (`ERR_NOT_RESOURCE_OWNER`) where the endpoint owns a resource, and standing (`ERR_ATTORNEY_NOT_AUTHORIZED`) on unscoped list endpoints — `auth.py:94-97` vs `auth.py:122-123`, callsites `routes_drafts.py:182`
- §2.2 bullet 1 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum characters — `envelope.py:20`
- §2.2 bullet 2 — insert — mismatch — `api_request_timestamp` comes from real wall-clock time, not the logical clock — `envelope.py:24`, `timeutil.py:84`
- §2.3 ¶1 — insert — ambiguity — non-integer `limit`/`offset` is 400; pagination bounds are checked *last* (after path existence/ownership) while declared filters are validated *before* path existence; id-valued filters are never resolved as FKs (empty page, not 404); undeclared query params ignored — `envelope.py:51-79`, `validation.py:166-201`, ordering visible at `routes_cases.py:97-101`, `routes_payees.py:125-128`
- §2.3 ¶2 — insert — ambiguity — ordering keys compared as the stored value (rendered string for instants); ties beyond `created_at` broken by server insertion order — `store.py:108-122`
- §2.4 ¶3 — revise+insert — ambiguity — clock is "the only clock for every domain purpose"; `current_utc` accepts `Z` or a numeric offset and is normalised to UTC — `timeutil.py:11-38`, `routes_ops.py:17-21`
- §2.4 ¶3 — insert — mismatch — `api_request_timestamp` is the sole wall-clock value; every resource instant/date comes from the logical clock — `envelope.py:24`
- §2.4 ¶4 — insert — ambiguity — sub-millisecond precision is truncated, not rounded; `current_utc` echo is the supplied string with whitespace stripped and never re-spelled; `previous_utc` of a never-set clock is `2026-08-01T00:00:00Z` — `timeutil.py:57-58`, `routes_ops.py:19-21`, `store.py:11,60-64`
- §2.5 ¶2 — insert — ambiguity — a zero divisor anywhere yields a quotient of zero, never an error/null — `calc.py:26,34,108`
- §2.6 ¶1 — insert — ambiguity — trailing slash equivalent to its absence — `app.py:24`
- §2.8 rung 3 — insert — ambiguity — JSON `null` == absent (default for optional, missing-field 400 for required); booleans/strings not accepted for integers; undeclared body fields ignored; absent/empty/`null` body read as `{}`; non-JSON or non-object body is 400; datetimes accept `Z` or offset — `validation.py:14-31,59-66`, `errors.py:122`
- §2.9 ¶2 — insert — ambiguity — recomputation always rewrites the five figures but versions the row unconditionally only for money-source creation, hold release, qualification, and a SHARED_PAYMENT distribution/void; receipt, resubmission and sweep-lapse bump `version` only when a figure moved; account creation leaves it at `version` 1 — `services.py:108-127`, `force=True` at `routes_participants.py:135`, `routes_holds.py:70`, `routes_drafts.py:402`, `routes_payees.py:113,175`; unforced at `routes_participants.py:91`, `routes_drafts.py:159,307`, `services.py:318`
- §3.4 coverture ¶ — revise — **mismatch** — PRD said a case without `marital_period_end` "cannot be priced this way"; impl prices it with the numerator cut off at the case's `valuation_date`. Revised to pin that, and to say the missing end date blocks the order only via the deficiency code — `calc.py:70-80`
- §3.5 projection ¶ — insert — ambiguity — the read never refuses for a missing baseline snapshot (growth 0, not `ERR_VALUATION_SNAPSHOT_MISSING`); a case with no operative `approach` returns null `effective_approach`, gross 0 and a zero skeleton while still reporting `assignable_base_cents`/`valuation_snapshot_count`; the read *does* require the operative plan account (`ERR_PLAN_ACCOUNT_NOT_FOUND`); basis carryover named as part of the skeleton — `services.py:206-243`, `services.py:74-80`
- §3.8 sweep ¶ — insert — ambiguity — `evaluated_count` was entirely unspecified: pinned as `len(expired_hold_ids) + len(expired_notice_ids) + len(closed_ap_account_ids)`, with phase-1 cascade-expired notices counted and lapsed cases / denied drafts not counted; lists are in phase processing order — `services.py:358-366`
- §3.8 Phase 1 — insert — ambiguity — with no non-terminal draft, the lapse skips the draft levels and leaves `review_status` alone but still moves the hold, restores balances, sets `LAPSED`, appends both letters and bumps the case `version` — `services.py:319-333`
- §3.8 Phase 3 — insert — ambiguity — processing order is `established_at` ascending, `created_at` tie-break — `services.py:347`
- §3.9 step 7 — insert — ambiguity — the 59-year-6-month advance clamps day-of-month to the last day of a short target month (31 Aug → 28/29 Feb) — `timeutil.py:102-108`
- §5 preamble — insert — ambiguity — `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405) and `ERR_INTERNAL` (500) use the same envelope but are deliberately outside the catalogue table — `app.py:38-57`

## Judged already uniquely pinned (no change)
`errors.py` catalogue and all 47 error→status mappings match §5 exactly; the 11 `VERSIONED` types and the three append-only types (§2.4); UUID `id` with no prefix; `created_at`/`updated_at` at three fractional digits and `fmt_domain_instant`'s variable-precision domain stamps (§2.4 pins both, including the 3.4 hold example); `touch` bumping `version` by exactly 1 (§2.10); default clock `2026-08-01T00:00:00Z`; `add_days` carrying time-of-day and strictly-greater-than expiry predicates (§3.4); every `enums.py` literal set and `PROCEDURE_TRANSITIONS` (§3.1); the five derived plan-account balances and the AP-account `ISSUED`-set reconciliation (§2.9); all of `gross_assigned_amount` including both ceilings and the zero floor, the coverture cap at 10000, `per_source_allocation`'s last-source residue, `period_growth_bps`, `credited_growth_bps` for both methods, `per_source_earnings` rounding order, `per_source_basis` rounding down, `shared_payment_per_period` (§3.4/§3.5); all seven `settle_distribution` steps, fee tiers, the 20000-cent taxable withholding floor and `tax_year` (§3.9); every `deficiency_codes` condition and the ASCII sort (§3.6); ordering helpers for money sources, snapshots, holds, drafts, notices, distributions, authorizations and communications (§3.2–§3.9, §4); `operative_draft`/`live_draft`/`latest_notice` selection; `hold_capacity_check` excluding the case's own hold; `expire_issued_notices`; `copy_operative_terms`; `baseline_snapshot`/`endpoint_snapshot`; `append_party_pair` ordering; tax-report field set and sign inversion; attorney window semantics (midnight-UTC `effective_from`, inclusive `expires_at`); ownership comparisons for Participant/AlternatePayee/Attorney; administrator/analyst ids never compared to entity ids. `start.sh`, `requirements.txt` and the `PORT` default are governed by `INSTRUCTION.md`, not the PRD, so no PRD passage was added for them.

Verbatim summary returned by Step 9 PASS 2 (routes_plans / routes_participants / routes_cases):

Pass 2 complete.

## Counts

- **PRD_COMPLETED.md before:** 470 lines / 108,728 chars → **after:** 470 lines / 111,776 chars. Still ends on `| `ERR_ASSIGNED_AMOUNT_ZERO` | 422 |`.
- **13 edits: 11 ambiguity-pins, 2 mismatch-revisions.** All in-paragraph; no new sections or paragraphs.

## Changes

- §2.6 — insert — ambiguity — the four body-borne identifiers are non-blank strings of ≤200 chars, so an out-of-shape value is `ERR_INVALID_REQUEST` one rung earlier, not a not-found — `routes_participants.py:35`, `routes_cases.py:45`, `routes_drafts.py:89,92`, `validation.py:48`
- §2.8 rung 3 — revise — **mismatch** — pass 1 claimed a non-JSON body is universally 400; the five body-less write ops (qualify, hold release, void, revoke, sweep) never parse the body, so anything sent with them is ignored — `routes_cases.py:171`, `routes_holds.py:55`, `routes_payees.py:151`, `routes_drafts.py:315`, `routes_ops.py:25`
- §2.11 — insert — ambiguity — with several authorizations for the addressed side, the most recently created `ACTIVE` one is resolved (else the most recently created of the rest); with none representing that side the scope rung simply passes — `routes_cases.py:182-191,204-209`
- §3.1 — revise — ambiguity — `model_language_version` is also non-blank — `routes_plans.py:40`
- §3.2 — insert — ambiguity — a future `participation_start_date` is `ERR_INVALID_REQUEST` (400) caught before `plan_id` resolves; `date_of_birth` is never compared to the clock or to the start date — `routes_participants.py:40,49-50,53-55`
- §3.2 — insert — ambiguity — opening a plan account does not move the participant row's `updated_at`/`version` (unlike enrolment, which versions the plan) — `routes_participants.py:74-92`
- §3.2 — insert — ambiguity — `basis_cents` > `balance_cents` is `ERR_INVALID_REQUEST` (400), evaluated before the path account resolves — `routes_participants.py:120-122`
- §3.2 — insert — ambiguity — a snapshot's `as_of_date` bears no required relation to the logical clock — `routes_participants.py:151`
- §3.2 — insert — ambiguity — recording a snapshot leaves the parent account's `updated_at`/`version` untouched — `routes_participants.py:160-167`
- §3.3 — insert — ambiguity — `valuation_date` needs no ordering relation to the marital bounds or the clock — `routes_cases.py:47`
- §3.3 — insert — ambiguity — the `expires_at`-vs-midnight and at-sign rules are 400s evaluated before the case path resolves; `expires_at` is persisted/echoed verbatim as supplied while `effective_from` is normalised to `YYYY-MM-DD` — `routes_cases.py:131-134,143-144`
- §3.3 — insert — ambiguity — inside the readiness rung the missing draft order is tested before the counsel authorization; a manual send leaves the case's `updated_at`/`version` untouched — `routes_cases.py:216-227`, `services.py:144-156`
- §3.5 — revise — **mismatch** — pass 1's "null `effective_approach` … whole skeleton at 0" was a false universal: with an `approach` override on a draft-less case the variant is named and run, all money figures stay 0, but `earnings_growth_bps` can be non-zero — `services.py:219-243`, `calc.py:83-87`

## Already uniquely pinned (no change)

Plan registration field set, ranges and defaults (45/60/548/3/5000/100000000, `requires_model_language` true, `permits_…` false) and `procedures_status` `DRAFT`; the three declared procedure transitions plus the publication guard and the per-transition plan version bump; derived `participant_count` with no status filter; enrolment recomputing `participant_count` and versioning the plan; `ssn_last4` four ASCII digits; one plan account per participant with five derived balances at 0 and `version` 1; money-source fields, duplicate `source_code` 409, unconditional account version bump, `source_code` ASCII ordering; snapshot duplicate 409, `as_of_date` ordering and filter; case intake defaults (INTAKE/NONE, five null terms), half-open marital overlap excluding `DENIED` cases, `ERR_MARITAL_PERIOD_OVERLAP`; authorization creation (`ACTIVE`/null `revoked_at`) versioning the case, and revocation versioning only the authorization with `ERR_AUTHORIZATION_NOT_ACTIVE`; correspondence field set, `SYSTEM`/`MANUAL` origin, `attorney_email` copied by value/null, `sent_at` ordering and the three filters; the `ALTERNATE_PAYEE` `FULL`-before-`QUALIFIED` ceiling and the absence of any ceiling for `PARTICIPANT`; projection's nine computed fields and its `ERR_PLAN_ACCOUNT_NOT_FOUND`; every role/ownership/standing gate and the filter-before-path-existence, pagination-last ordering from §2.3/§2.8.

Verbatim summary returned by Step 9 PASS 3 (routes_drafts / routes_holds / routes_payees / routes_ops):

Pass 3 complete. Final verification passed: 470 lines (unchanged), 29 headings, 94 table rows, 4 code fences — all identical to `PRD_FINALIZED.md`; ends on `` | `ERR_ASSIGNED_AMOUNT_ZERO` | 422 | ``; `cmp` confirms it differs from `PRD_FINALIZED.md`.

## Counts

- **Before my pass:** 470 lines / 111,776 chars → **after:** 470 lines / 116,344 chars (+4,568)
- **Ambiguity-pins: 11 · Mismatch-revisions: 6** (17 changes total, all in-paragraph; no new sections, no new paragraphs)

## Changes

- §2.1 — insert — ambiguity — a `Participant` reaching a segregation hold resolves the hold's `plan_account_id`, then compares that account's `participant_id` — `routes_holds.py:27-29`
- §2.1 — insert — ambiguity — a payee reaching a 1099-R line compares the line's denormalised `alternate_payee_account_id` — `routes_payees.py:190-192`
- §2.1 — insert — ambiguity — the three collection-root lists (draft orders, holds, tax reports) silently narrow to the caller's own rows instead of refusing, and `total_count` counts only the narrowed set; operator roles are never narrowed — `routes_drafts.py:192-207`, `routes_holds.py:46-49`, `routes_payees.py:212-213`
- §2.6 — insert — ambiguity — on receipt the operative-plan-account resolution runs after ownership/standing and **before** `expected_case_version`, so `ERR_PLAN_ACCOUNT_NOT_FOUND` beats a stale version — `routes_drafts.py:99-107`
- §2.7 — insert — ambiguity — both `expected_*_version` fields are integers ≥ 0; a negative is rung-3 `ERR_INVALID_REQUEST` — `routes_drafts.py:90`, `routes_payees.py:57`
- §2.8 rung 13 — revise — mismatch — rung 13 omitted rejection-notice issuance from the `ERR_SEGREGATION_WINDOW_EXPIRED` scope even though §3.6 states it; added to both the clause and the "Applies to" list — `routes_drafts.py:231`
- §3.4 — insert — ambiguity — the formula-conditional and shared-payment-end-date rules are rung-3 `ERR_INVALID_REQUEST` reported **before** `qdro_case_id` resolves — `routes_drafts.py:34-60, 88-96`
- §3.4 — revise — mismatch — PRD claimed `attorney_authorization_id` "is null" when a participant/administrator lodges; it is optional for every role, the equality rule binds only an acting `Attorney`, and a value any role cites is resolved and stored verbatim — `routes_drafts.py:92, 97-100`
- §3.4 — revise — mismatch — the `RECEIPT_ACKNOWLEDGMENT` entry and the case `version` bump were scoped to the first receipt; both happen on **every** receipt, superseding included — `routes_drafts.py:160-162`
- §3.4 — insert — ambiguity — the hold re-size reaches the hold only while `HELD` and always bumps the hold's `version` even at an identical amount; receipt has no review-status gate (a `QUALIFIED`/`DENIED` case still accepts a draft, `review_status` unmoved); a later receipt whose hold already left `HELD` sizes and capacity-tests but places/re-sizes nothing — `routes_drafts.py:110-158`
- §3.4 — revise — mismatch — PRD said sizing is "recomputed ... again at qualification"; qualification does **not** re-size, it converts the hold's stored `hold_amount_cents` while spreading it over the account's *current* assignable base — `routes_drafts.py:352-354`
- §3.6 — revise — mismatch — resubmission also overwrites `document_reference` (omitted from PRD's overwrite list) — `routes_drafts.py:276, 296`
- §3.6 — insert — ambiguity — no correspondence entry is appended on a resubmission — `routes_drafts.py:296-309`
- §3.7 — revise — mismatch — the seven-condition list contradicted §2.8 and impl by putting `UNDER_REVIEW` before segregation of duties; order swapped and the consequence pinned (a `DEFICIENT` draft offered by its own reviewer reports `ERR_SEGREGATION_OF_DUTIES`) — `routes_drafts.py:320-327`
- §3.8 — insert — ambiguity — `SEGREGATION_LAPSED` is a declared `denial_reason` literal, so supplying it clears rung 3 and is refused `ERR_DENIAL_NOT_PERMITTED` (409), not `ERR_INVALID_REQUEST` — `routes_drafts.py:413, 444`
- §3.9 — insert — ambiguity — a shared-payment account with `per_period_amount_cents` 0 can never distribute (gross ≥ 1); reached when the operative `assigned_percentage_bps` is null, which a `FLAT_DOLLAR` order may omit — `routes_payees.py:59, 72-74`, `calc.py:159-161`
- §3.9 — insert — ambiguity — a shared-payment distribution debits only each source's `balance_cents`, never `basis_cents`, so `after_tax_basis_cents` stands and later slices recover basis from the same pool; issuance appends no correspondence, so `DISTRIBUTION_CONFIRMATION` only ever arrives via a manual send — `routes_payees.py:110-115`

Two of my own inserts were self-corrected before finishing: a false universal claiming a `FLAT_DOLLAR` case "carries no `assigned_percentage_bps`" (impl only makes it *optional* there), and a claim that a post-terminal receipt never re-sizes a hold (false for a `DENIED` case, whose hold stays `HELD` until an explicit release).

## Judged already uniquely pinned (no change)

Role gates and §4 rows for all 13 endpoints in the partition; `ERR_DRAFT_ORDER_NOT_FOUND` / `_HOLD_` / `_AP_ACCOUNT_` / `_DISTRIBUTION_` / `_TAX_REPORT_NOT_FOUND`; the four-gate resubmission order and its window-before-cap rule; `notice_sequence` = count+1 and the notice's field set, deadline and `ISSUED → CURED`; the deficiency-notice cascade (draft → `DEFICIENT`, `reviewed_by_user_id`, case → `DEFICIENT`, PARTICIPANT-FULL-then-PAYEE-LIMITED pair); the whole 7-level qualification cascade including `CONVERTED` vs `RELEASED`, the AP-account field set per approach, the L5 balance+earnings+basis debit, `force`-recompute, and the FULL/FULL communication pair; every `_denial_supported` predicate (including that `RESUBMISSION_WINDOW_CLOSED` does not require the notice to still be `ISSUED`); denial leaving the hold `HELD`; the release gate order and its cascade; all list orderings and filters in the partition (`received_at`, `notice_sequence`, `placed_at`, `issued_at`, `written_at`, each with the `created_at` tie-break); the 7-step distribution settlement and its `CODE_2`/`CODE_7`/`CODE_G` rules; funding-pool selection and capacity per `payment_mode`; the `SEPARATE_INTEREST` auto-close at balance 0; the four-level void cascade and its corrective-line signs; the clock echo/`previous_utc` contract and the sweep report shape.
