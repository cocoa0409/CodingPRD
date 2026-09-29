# Worklog — task_2716_store_closing_going_out_of_business_sale

## Step 1: Create task directory — 2026-09-04T11:01:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2716_store_closing_going_out_of_business_sale` and `.../workspace` via `mkdir -p`. Index 2716 was pre-assigned by the orchestrating command; no scan of ./tasks/ was performed (other pipelines run concurrently on this host).

## Step 2: Generate Scaffold — 2026-09-04T12:39:00.000Z

All three artifacts are complete and the lint is clean.

**Verdict (verbatim from `scaffold_lint.py`):**

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2716_store_closing_going_out_of_business_sale/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2716_store_closing_going_out_of_business_sale/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2716_store_closing_going_out_of_business_sale/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    61
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     65
  Calls scanned (§1.8+§1.9):  1158

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2716_store_closing_going_out_of_business_sale/`)
- `SCAFFOLD.yaml` — 3466 lines (182 KB); top-level keys only `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — contains neither design key.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2137 lines (135 KB); single top-level key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 5042 lines (319 KB); single top-level key `scaffold_corner_design`.

**§1.0–§1.7 surface:** 12 entities, 11 state machines, 2 concurrency rules, 10 calculations, 39 validations (priority ladder 10->86), 61 endpoints, 65 errors, 5 roles (`role_model: segregation_of_duties`, `consistency_model: immediate`, layers: dual_variant_calculation / cascading_side_effects / rate_threshold_triggers / optimistic_concurrency).

**§1.8 rule ids × instances (18 total, 2 each):** dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant.

**§1.9 sections × instances (84 total, of which 19 are `excluded_because` stubs):** entities 11, state_machines 16, calculations 14, validations 13, endpoints 5, errors 13, rbac 6, cross_cutting_layers 5, consistency_model 1.

**Cross-checks run:** 101 instance names unique across both design files; every stub's `difficulty_instance` resolves to a real §1.8 instance; all 65 error ids are referenced by at least one design instance; every one of the 61 §1.5 endpoints is exercised by at least one structured call.

**Scaffold self-inconsistencies found and fixed in `SCAFFOLD.yaml` while writing the corner walk** (the §1.9 iteration doing its job): added the missing `SELLING -> SUSPENDED` Store transition for `POST /stores/{id}/suspend`; disambiguated p55's "augmentation-bearing claim" to the two price-comparison codes; added `GET /inventory-lots/{id}` so `ERR_INVENTORY_LOT_NOT_FOUND` is reachable; reconciled `guaranty_pct` range with p30/p82 and the "must be null" wording; and — for RBAC — replaced p15's "five fixed role identities" with prefixed opaque identities (`lc-*`, `rc-*`, `co-*`, `so-*`, Store id for StoreManager) plus a p28 note recording that the licence decision is the only endpoint where segregation of duties can actually collide, since on the other four the submitting and deciding roles are structurally different.

## Step 3: Copy shared files — 2026-09-04T12:40:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T12:59:00.000Z

PRD generation is complete and verified.

## Deliverable

`workspace/PRD.md` — **476 lines**, written incrementally (one `Write` + nine `cat >>` heredoc appends + three targeted `Edit`s). Ends cleanly at the final row of the §5 error table; nothing truncated.

## Section list

- `# Store Closing Liquidation API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (+ the two fixed sub-headings) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and the Logical Clock · 2.5 Money, Ratios and Rounding Discipline · 2.6 Version Pinning on Cadence and Settlement Writes · 2.7 Segregation of Duties · 2.8 The Compliance Posture Gate · 2.9 Cascade Propagation and Roll-Up Consistency · 2.10 Path Hierarchy and Resolution Order · 2.11 Validation Order (39-step ladder) · 2.12 Status Vocabularies
- `## 3. Business Logic & Workflows` — 3.1 Establishing the Agency Agreement and Its Closing Stores · 3.2 Valuing the Selling Floor: Inventory Lots and Projected Recovery · 3.3 Licensing the Sale, Advertising Claims and the Compliance Cascade · 3.4 The Markdown Cadence and Sell-Through Escalation · 3.5 Augmentation Merchandise: Disclosure, Cap and Unit Conservation · 3.6 Reporting and Posting Selling Days · 3.7 Staffing Wind-Down, Retention Bonuses and the Expense Ledger · 3.8 Lease Disposition, Fixture Sale and the Landlord Surrender Waterfall · 3.9 Final Settlement Accounting
- `## 4. API Endpoints` — 61-row table (Method | Path | Description | Authorized Role(s))
- `## 5. Error Codes` — 65-row table (Error ID | HTTP Status Code)

## Coverage audit — three Hard Contracts

**Contract 1 — Field-Name Coverage: PASS.** Programmatic diff of 179 required identifiers (all entity field names across the 12 entities, every endpoint `input` request-body field and query/path param with `?` stripped, every key of the multi-key `output` blocks — `store_count`, the five sweep tallies, `current_utc` etc. — plus the four `common_fields`): **0 missing**, each present verbatim inside backticks. Additionally verified: all 65 `error_id`s appear in backticks; all 78 enum values from `one of {...}` constraints and all 45 state-machine state names appear in backticks (the four that appear only inside transition arrows — `PENDING_RETAILER_APPROVAL`, `DENIED`, `EXPIRED`, `REVOKED` — are also now enumerated explicitly in the new §2.12).

**Contract 2 — Rule Coverage: PASS.** All 39 validations mapped priority-by-priority in §2.11 with error id and `applies_to` scope, and each re-stated in context in §3. All 58 state-machine transitions represented (27 in prose rather than literal `A -> B` arrow form, e.g. "defined from `SUBMITTED` and from `APPROVED`"). Both `concurrency_rules` (§2.6) with exact OCC field, error id and 412. All 10 calculations reconstructable with every constant given numerically: category sell-through 0.85/0.80/0.70/0.95/0.60/0.90, fee tiers 0.0200/0.0350/0.0500 at the 0.60/0.80 boundaries, escalation band 0.05 / step 0.05 / cap 0.20, `MAX_DISCOUNT_PCT` 0.90, attendance floor 0.90, holdover multiplier 1.5, cap comparison inclusive-at-equality, allocation order "`created_at` ascending then `category` enum name ascending", remainder side = retailer, posture thresholds 1 and 3. Cross-entity cascades written as explicit hop chains (six-hop close-selling, five-hop revoke, sweep fan-out, consignment receipt, surrender, finalize). Field-level defaults, sibling-branch symmetry (`APPROVE`/`RETURN_FOR_REVISION`, `APPROVE`/`DENY`, `POST`/`REJECT`, `APPROVE`/`VOID`, `COUNTER`/`ACCEPT`/`REJECT`, `ACCEPT`/`DISPUTE`) and all compensating actions (return-unsold, expense void) covered. Endpoint table roles diffed against the scaffold: 0 mismatches. Error-table statuses diffed: 0 mismatches. §2.2 block diffed byte-for-byte against `section-2.2-response-structure.md`: identical.

**Contract 3 — §3 Path Purity: PASS.** Scan of all 998 backticked tokens in §3: zero contain `/`, zero are method+path tokens, and zero bare `GET`/`PUT`/`PATCH`/`DELETE` or slash-paths appear outside backticks. One token reads `POST` — that is the legitimate `decision` enum value of the sales-day review (`POST` | `REJECT`) from the scaffold, not an HTTP method. Endpoints in §3 are referenced only by state-transition framing, role+action verb, or capability description. URL paths appear only in §2 and §4, which the skill permits.

**No design-index leakage.** Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced at any point. A grep of PRD.md for `difficulty`, `scaffold`, `corner_design`, `test_recipe`, `1.x`, `depth`, `breadth` returns zero hits, as does a grep for the fuzzy words `approximately`/`roughly`/`about N`.

## Scaffold contradictions resolved (implementer-visible choices)

1. `limit` bounds — envelope says max 100, validation priority 30 says `[1,200]`; chose **1-100**, out-of-range -> `ERR_INVALID_REQUEST`.
2. `selling_start_date` on engagement approval — state machine says `sale_start_date`, endpoint table says logical clock date; chose **`sale_start_date`**.
3. `selling_start_date` on licence approval — state machine says `period_start_date`, endpoint table says clock date; chose **`period_start_date`**.
4. `discount_pct` monotonicity — field says `>=` predecessor, validation 68 says strictly greater; chose **strictly greater**.
5. `guaranty_pct` under `FEE_BASED` — field says "must be null", validation says `== 0`; wrote **"no value at all or exactly 0"**.
6. Expense shares before approval / on void — field defaults say `0`, one endpoint `side_effects` line says `null`; chose **0** (two sources to one).
7. Submit-for-approval's store-count and original-lot preconditions carry no scaffold error id; mapped to **`ERR_ENGAGEMENT_STATE_INVALID`** and said so explicitly.
8. Worksheet `SHARED` expense rounding is once on the total while per-item shares round individually — the PRD states both and warns they may differ by a few cents, rather than silently reconciling them.

Orchestrator verification: `wc -l` = 476, `tail -25` ends at the complete final error-table row `| ERR_ECONOMICS_CONFIG_INVALID | 422 |`; heading scan shows all of §1-§5 present. Not truncated — no regeneration needed.

## Step 5: Generate Unit Tests — 2026-09-04T16:35:00.000Z

Done. Both output directories are complete and verified.

## Files written (task root, never under `workspace/`)

`test_helpers/` — 9 files, 2,318 lines (unchanged this segment): `__init__.py` 43, `api_client.py` 347, `api_errors.py` 144, `assertions.py` 394, `constants.py` 69, `factories.py` 158, `fixtures.py` 639, `test_users.py` 67, `types.py` 457.

`test_suite/` — `conftest.py` 74 plus 19 test modules, 9,185 lines. New in this segment:
- `test_18_role_authorization.py` — 749 lines, 15 tests (all 6 non-stub `Corner/rbac` instances)
- `test_19_versioning_and_visibility.py` — 463 lines, 9 tests (3 non-stub `Corner/cross_cutting_layers` + the 1 `Corner/consistency_model` instance)

## Tests emitted

- Queue A (`Design: Difficulty/...`): **77 tests** over all **18** depth instances (every instance >=2 tests).
- Queue B (`Design: Corner/...`): **168 tests** over **64** of the **65** non-stub breadth instances (every instance >=1 test). The 19 `excluded_because:` corner stubs were not translated, as specified.
- Total **245 tests**, 82 distinct design instances.

## Skipped instances

1. `Corner/errors/pending_retention_bonus_cannot_be_paid` — **non-unique-derivability**. The design asserts `ERR_BONUS_NOT_EARNED` (409) for paying a `PENDING` bonus on a `SELLING` store, but §2.11 puts state admissibility (step 10, which owns `ERR_STORE_NOT_SELLING`) ahead of bonus eligibility (step 38), and the PRD says "The store must already be `CLOSED` or `SURRENDERED`, otherwise the payment is refused with `ERR_STORE_NOT_SELLING`". Both errors are defensible for the declared setup, and the aspect cannot be re-staged legitimately (the close-selling cascade settles every `PENDING` bonus, so a `CLOSED` store can never hold one). No weakening, no xfail, no placeholder emitted.

No other instance failed the PRD-first filter. One faithful-translation adjustment worth flagging: the consistency instance asserts `realized_gross_recovery_cents` on the **Engagement** read, a field the PRD declares only on `Store` and on the recovery-summary read — the engagement assertion is expressed as `gross_recovery_cents` / `original_net_sales_cents` (the PRD's own names for that figure, §3.7), with `realized_gross_recovery_cents` asserted on the store and on the summary where the PRD does declare it.

## Verification

`ast.parse` + `python3 -m py_compile` clean on all 29 generated `.py` files; tag validator `problems: 0` with exactly one `Design:` line last in every docstring and no unknown instance names; quote validator `bad quotes: 0` across the whole suite; zero unused imports; every `api_client.*` method used exists on `ApiClient` (one fix applied: `revoke_license` -> `revoke_gob_license`); every name imported from `test_helpers` resolves; no `scaffold` references anywhere; no duplicate class/method names; no stray `test_helpers/`, `test_suite/` or `conftest.py` under `workspace/`; `workspace/implementation/` was never read, listed or touched.

Orchestrator verification: `test_helpers/` and `test_suite/` both sit at the task root; `find workspace -name test_helpers -o -name test_suite -o -name conftest.py` returns nothing; 20 files in test_suite/, 245 `def test_` functions total.

## Step 6: Generate Implementation — 2026-09-04T15:30:00.000Z

Implementation complete. Smoke server (PID 1647199, port 18716) shut down by captured PID only; port confirmed closed. No broad pkill was used.

## Location
`workspace/implementation/`

## Modules (17 .py, 3731 lines + start.sh 10 + requirements.txt 1)

Infrastructure
- `money.py` 50 — Decimal helpers, `round4`, ROUND_HALF_UP/FLOOR/CEILING money primitives
- `clock.py` 82 — logical clock (default `2026-08-01T00:00:00Z`), `POST /_clock/set_current_utc`, ISO timestamps with exactly 3 fractional digits
- `db.py` 159 — in-memory dicts keyed by uuid4, `_seq` monotonic tie-break, per-parent index accessors. Nothing seeded at boot
- `errors.py` 107 — 66-id catalogue with fixed HTTP statuses, `ApiError`
- `response.py` 59 — envelope (`meta`/`response_type`/`data`), `req_` + 20 uppercase alnum request ids
- `shape.py` 183 — typed field extractors, pagination (limit 10/1/100, offset >=0)
- `auth.py` 78 — `X-User-ID` prefix routing (`lc-`/`rc-`/`co-`/`so-`, else existing Store id -> StoreManager), `ERR_UNKNOWN_ACTOR`, store scoping, SoD guard
- `helpers.py` 77 — 404 resolution, posture gates, pagination assembly
- `calc.py` 589 — all 10 calculations: store/engagement recompute, projected recovery, sales-day allocation with trace note, augmentation cap, delivery-slot capacity, escalation ladder, retention bonus, lease waterfall, fee-tier bands, settlement split
- `serializers.py` 299 — 12 entity serializers with declared field order and types
- `app.py` 58 — blueprint registration, `strict_slashes=False`, `sort_keys=False`, ApiError/HTTPException/Exception handlers

Routes (61 endpoints, verified by route introspection against the PRD §4 table)
- `routes_engagement.py` 446 — jurisdictions, engagements, approval workflow, wind-down, compliance sweep, recovery summary, clock
- `routes_store.py` 437 — stores, inventory lots, sales days, employees, lease-disposition create, close-selling cascade, resume
- `routes_license.py` 355 — GOB licences (apply/decide/revoke 5-hop cascade), markdown stages (create/activate/checkpoint escalation)
- `routes_money.py` 378 — expense items, lease negotiation + surrender waterfall, settlements (create/propose/respond/finalize)
- `routes_augmentation.py` 237 — consignments, disclosure filing, receive with cap check, return-unsold
- `routes_staffing.py` 137 — employee reads, employment state machine, bonus payment, sales-day review

All files `py_compile` clean; no file was written in a single oversized Write (chunked heredoc appends throughout).

## Smoke results (5 rounds, fresh boots)

Round 4 — full happy-path lifecycle: jurisdiction -> HYBRID/SHARED engagement -> store -> lot -> lease disposition -> submit/approve (store SELLING) -> sales day POST with allocation trace -> expense APPROVE (SHARED split 18000/12000) -> recovery-summary -> offer/ACCEPT -> close-selling cascade (accrual 10000; expense totals 40000/24000/16000 incl. auto PAYROLL) -> surrender waterfall (holdover 2 days, penalty 30000, rent 100000, unpaid 280000, residual 0) -> wind-down -> settlement propose (gross 500000, ratio 0.5, rate 0.02, fee 10000, retailer 484000, liquidator -24000) -> dispute/re-propose/accept -> finalize (items SETTLED, engagement CLOSED). Settlement identity 484000 + (-24000) + 40000 = 500000 exactly.

Round 5 — compliance and negative paths: `ERR_LICENSE_PERIOD_TOO_LONG`, `ERR_DUPLICATE_CLAIM_CODE`; licence revoke cascade (licence REVOKED -> store SUSPENDED/LICENSE_REVOKED -> active stage CLOSED/LICENSE_LOST -> strike 1 -> posture RESTRICTED); stage authoring then blocked with `ERR_ENGAGEMENT_COMPLIANCE_RESTRICTED`; resume blocked `ERR_LICENSE_NOT_ACTIVE`; clock advance + compliance sweep returned `{expired_license_count 1, closed_stage_count 0, suspended_store_count 1, compliance_strike_count 2, RESTRICTED}`; third strike -> FROZEN with expense submission blocked `ERR_ENGAGEMENT_COMPLIANCE_FROZEN`; three-store close -> WIND_DOWN.

Three probes that initially looked like defects were confirmed to be smoke-script artefacts, not bugs: a lease disposition created after `close-selling` (PRD §2.11 step 10 / SCAFFOLD priority 40 forbid any store child on a CLOSED store), `ERR_UNAUTHORIZED` before SoD (role check priority 20 precedes SoD 28), and `ERR_SALES_DAY_OUT_OF_WINDOW` before the totals check (window 64 precedes totals 86). Same for the final cooling-off probe, which correctly returned `ERR_STORE_STATE_INVALID` because the store had already closed.

Key documented conflict resolutions: shape (30) before existence (35) per the scaffold's numeric priorities, overriding the PRD §4 prose "404 before any payload is examined"; notice-short (66) before fixture-below-reserve (72); expense shares initialise to `0` not null; licence approval sets `selling_start_date = period_start_date` while engagement approval uses `sale_start_date`; recomputation alone never bumps versions.

## Step 7: Iterate Tests + Fixes — 2026-09-04

Three 8-round parallel stability sweeps (`per-test-server`, 245 tests, `setsid nohup`, no early exit).
Round-1 baseline 228/245 in all 8 rounds; round 2 243/245 in all 8; round 3 **245/245 in all 8**.
Every failure was deterministic across all 8 rounds — no flakiness surfaced at any point.

### Tests deleted
None. Every failing assertion traced to a verbatim PRD sentence; all 17 were either a test-artifact
inconsistency (12) or a genuine implementation defect (5). 245 tests remain, no skip/xfail anywhere.

### test_helpers/ fixes
- `assertions.py::assert_inventory_lot` — asserted `cost_value_cents == units_initial * unit_cost_cents`;
  §3.2 says "the initial units **less any returned units**", so a returned augmentation lot legitimately shrinks.
- `assertions.py::assert_lease_disposition` — required the waterfall figures (`holdover_days`,
  `holdover_penalty_cents`, the four `allocated_*`, `unpaid_landlord_balance_cents`,
  `residual_to_retailer_cents`) to be integers on a `DRAFT` row; §3.8 opens a disposition
  "with every negotiated, computed, and allocation field unset". Now status-aware on `surrendered_at`.
- `assertions.py::assert_settlement` — same defect on the split figures plus `recovery_ratio` / `fee_rate`;
  §3.9 opens a worksheet "with every split figure unset" and a proposal is what "stamps `computed_at` …
  and writes every computed money field". Now status-aware on `computed_at`.
- `types.py` — `LeaseDisposition` and `Settlement` TypedDicts widened to `Optional[int]` / `Optional[float]`
  on the same computed fields, matching the two validators above.

### test_suite/ fixes
- `test_18_role_authorization.py::_license_pending_store_with_an_application_by_the_first_officer` —
  passed `applied_by=COMPLIANCE_OFFICER_ID` (a bare `str`) where `apply_for_license` takes a headers dict,
  producing `AttributeError: 'str' object has no attribute 'items'`. Now `make_compliance_headers(...)`.
- `test_14_money_and_unit_calculations.py::_store_whose_older_lot_is_the_home_one` — created both lots
  under one pinned clock instant, so their `created_at` were identical and §3.6's documented tie-break
  ("the lot whose `category` enum name sorts lexicographically earlier first") correctly took APPAREL
  ahead of HOME. The clock is now advanced between the two creates, still inside 2026-09-15 so no date
  arithmetic moves, which is what the test's own docstring intends ("chronological order beats category order").
- `test_13_lifecycle_state_transitions.py::test_a_lease_disposition_opens_in_draft_at_round_zero` and
  `::test_accepting_a_draft_worksheet_is_refused_and_writes_no_money` — asserted `== 0` for fields the PRD
  declares "unset". The PRD spends the two words distinctly (§3.7: "`served_days` and `earned_bonus_cents`
  both 0, and `notice_given_date`, `termination_date`, and `bonus_paid_at` all unset"), so "unset" is
  uniquely null. Assertions tightened to `is None` (and widened to cover the other two negotiated fields).

### implementation/ fixes
- `routes_store.py::create_lot` + `db.py::refresh` — filing a lot bumped the owning `Store.version` while
  the identical roll-up onto the `Engagement` did not. §3.2's lot-filing paragraph names no version
  increment on either row (contrast §3.4 "increments the store's `version` by 1" and §3.3 "the store's
  `version` increments alongside the licence's", where the PRD says so explicitly). New `db.refresh()`
  refreshes `updated_at` without bumping `version`, making both ends of the spine consistent.
- `routes_license.py::create_stage` — computed the sequence predecessor from the stages *surviving* the
  supersede, pre-excluding the rows it was about to void, so an otherwise valid third stage authored with
  `supersede_overlapping=true` was refused `ERR_STAGE_SEQUENCE_INVALID`. §2.11 puts the overlap check at
  priority 18 and the sequence check at 25, both ahead of any write, so the predecessor is read from the
  stages "not been voided" as the request found them.

### Final sweep
All 8 rounds `passed 245 / total 245`, `failed 0`, `errors 0`, `skipped 0` (~437s per round).

### Step 7 — subagent's returned summary, verbatim (orchestrator-pasted)

All 8 parallel rounds are fully green.

**Iterations run:** 3 full 8-round parallel sweeps (245 tests each, `per-test-server`, wrapped in `setsid nohup`). Baseline 228/245 -> 243/245 -> **245/245**. Every failure was deterministic in all 8 rounds; no flakiness ever surfaced, so no failure was load-induced.

**Tests deleted:** none. All 17 baseline failures traced to a verbatim PRD sentence and resolved as either a test-artifact inconsistency or a real implementation defect. 245 tests remain; no `skip`/`xfail` anywhere; no assertion downgraded to an HTTP-status check.

**Fixes to `test_helpers/`**
- `assertions.py::assert_inventory_lot` — asserted `cost_value_cents == units_initial * unit_cost_cents`; §3.2 says "the initial units **less any returned units**", so a returned augmentation lot legitimately shrinks.
- `assertions.py::assert_lease_disposition` — demanded integers for `holdover_days`, `holdover_penalty_cents`, the four `allocated_*`, `unpaid_landlord_balance_cents`, `residual_to_retailer_cents` on a `DRAFT` row; §3.8 opens a disposition "with every negotiated, computed, and allocation field unset". Now status-aware on `surrendered_at` (still strict once surrendered).
- `assertions.py::assert_settlement` — same defect on the split figures plus `recovery_ratio`/`fee_rate`; §3.9 opens a worksheet "with every split figure unset". Now status-aware on `computed_at`.
- `types.py` — `LeaseDisposition`/`Settlement` TypedDicts widened to `Optional` on the same computed fields.

**Fixes to `test_suite/`**
- `test_18::_license_pending_store_with_an_application_by_the_first_officer` — passed a bare `str` where `apply_for_license` takes a headers dict (`AttributeError: 'str' object has no attribute 'items'`); now `make_compliance_headers(...)`.
- `test_14::_store_whose_older_lot_is_the_home_one` — created both lots under one pinned clock instant, so their `created_at` were identical and §3.6's tie-break on `category` correctly took APPAREL ahead of HOME, defeating the test's own stated intent. Clock now advances between the creates, still inside 2026-09-15 so no date arithmetic moves.
- `test_13` (2 tests) — asserted `== 0` for fields the PRD declares "unset". §3.7 spends both words distinctly ("`served_days` and `earned_bonus_cents` both 0, and `notice_given_date` ... all unset"), so "unset" is uniquely null; tightened to `is None` and extended to the other negotiated fields.

**Fixes to `implementation/`**
- `routes_store.py::create_lot` + new `db.py::refresh()` — filing a lot bumped `Store.version` while the identical roll-up onto the `Engagement` did not. §3.2's lot-filing paragraph names no increment on either row, unlike §3.4 ("increments the store's `version` by 1") and §3.3 ("the store's `version` increments alongside the licence's"). `refresh()` updates `updated_at` without bumping `version`, making both ends of the spine consistent. Fixed 5 tests.
- `routes_license.py::create_stage` — computed the sequence predecessor from the stages *surviving* the supersede, pre-excluding rows it had not yet voided, so a valid third stage with `supersede_overlapping=true` was refused `ERR_STAGE_SEQUENCE_INVALID`. §2.11 puts overlap at priority 18 and sequence at 25, both ahead of any write. Fixed 2 tests.

**Final per-round numbers** (quoted from `workspace/implementation/results.$i.json`): rounds 1-8 each `passed 245`, `failed 0`, `errors 0`, `skipped 0`, `total 245` (~437 s/round).

**Orchestrator independent verification:** all 8 `results.*.json` exist (83 KB each, written 15:35) and each parses to `passed 245 / failed 0 / errors 0 / skipped 0 / total 245`. Step 8 is NOT skipped — Step 7 applied 2 `implementation/` fixes.

## Step 8: Finalize PRD — 2026-09-04T15:47:00.000Z

`PRD_FINALIZED.md` written. **476 lines -> 476 lines (0.0% line delta); 113,572 -> 115,556 bytes (+1.75%).** No new sections (5 `##`, 21 `###`, unchanged). 6 targeted edits, all tracing to the two `implementation/` fixes and one `test_helpers/assertions.py::assert_settlement` fix in `<step_7_diff>`.

### Changes

- **§2.4 — revise** — added that a recomputation rewriting only a row's own derived roll-up figures is not on its own a version-bumping "mutation", deferring to §2.9/§3 per operation — `db.py:55,64` (`touch` vs new `refresh`), `routes_store.py:60-66`
- **§2.6 — revise** — the list of what advances a store's `version` no longer includes "its inventory"; now cadence / licence state / augmentation supply / units a posted selling day consumes, with lot filing explicitly excluded — `routes_store.py:66` vs `routes_license.py:254`, `routes_augmentation.py:191,234`, `routes_staffing.py:133`
- **§2.9 — revise** — qualified the blanket "affected rows have their `updated_at` refreshed and their `version` incremented": a row reached only through the roll-up, whose own status and filed fields did not move, may stay at its current `version`; §3.2 pins lot filing as such a case — `calc.py:112-229` (no version writes in `recompute_store`/`recompute_engagement`/`recompute_chain`)
- **§3.2 — insert** — lot filing is not versioned on either end of the spine: lot opens at `version` 1, store's and engagement's `version` unchanged (and the note that this is what makes `expected_store_version` observed before filing still valid); consignment-receipt lots explicitly excluded, deferring to §3.5 — `routes_store.py:59-67`
- **§3.4 — insert** — the "stages that have not been voided" set is read as the request found the store, *before* this request's own supersede voids; a stage about to be superseded still counts toward the highest index and may still be the monotonicity predecessor — `routes_license.py:210-235`
- **§3.9 — revise** — a `DRAFT` worksheet opens with every figure the proposal would compute unset, `recovery_ratio` and `fee_rate` included, each null rather than zero; `dispute_round` at 0, `dispute_reason` unset — `routes_money.py:215-236`

### Per-edit pre-edit search log

1. **§2.4** — (a) subject: does a derived-only recompute count as a version-bumping mutation. (b) grepped every `db.touch`/`db.refresh` callsite (60 sites across all 7 route modules + `calc.py`); read `db.py:55-70`, `calc.recompute_store/recompute_engagement/recompute_chain`, `routes_store.create_lot`, `routes_license.create_stage`/`checkpoint_stage`, `routes_staffing.review_sales_day`, `routes_money.decide_expense_item`, `routes_engagement.recovery_summary`. (c) Found counter-examples in both directions — `checkpoint_stage:354` bumps the store on a derived-only recompute, `decide_expense_item:114` bumps the engagement though §3.7 never names it, while `create_stage:255` and `review_sales_day:136` leave the engagement alone. A universal "roll-up never bumps" would have been false, so the wording was softened to "not on its own such a mutation ... settled per operation", deferring rather than asserting.
2. **§2.6** — (a) subject: the enumerated triggers of a store `version` advance. (b) enumerated every store mutation: `create_lot` (no bump), `create_sales_day`/`create_employee`/`create_lease`/`create_license`/`create_expense_item` (no bump), `create_stage`/`checkpoint_stage` (bump), `activate_stage` (no bump), `review_sales_day` POST branch (bump), `receive`/`return_consignment` (bump), `suspend`/`resume`/`close_selling` (bump), `surrender_lease:209` (bump), `decide_license` approve (bump), `revoke_license` when selling (bump), sweep expiry (bump). (c) Left "its cadence" and "its licence state" verbatim despite `activate_stage` and a `DENY` decision not bumping (pre-existing looseness, off the Step 7 site); only replaced "its inventory" with the narrower posted-selling-day clause plus the explicit lot-filing carve-out.
3. **§2.9** — (a) subject: version/updated_at on roll-up-only rows. (b) same enumeration as (1), plus checked `serializers.py` exposes both `updated_at` and `version` on all twelve types, and that no `db.refresh` exists for the engagement anywhere. (c) Because the engagement's `updated_at` is *not* refreshed by a roll-up while the store's is (`routes_store.py:66`), the sentence was phrased as a qualification ("may legitimately be left at the `version` it already held") rather than a rule about `updated_at`, and points at §3.2 for the one pinned case.
4. **§3.2** — (a) subject: every row a lot creation touches. (b) read `routes_store.create_lot:40-67`, `routes_augmentation.receive_consignment:180-200` (the other lot-creating path — store *is* touched there), `calc.recompute_store`, `db.insert` (version 1), plus §2.6's `expected_store_version` pin and `test_19` which reads store version live. (c) Scoped the claim to "filing a lot through the store's own inventory collection" and added the explicit sentence handing the receipt-created lot back to §3.5, so the augmentation path is not mis-described.
5. **§3.4** — (a) subject: the stage set from which the sequence predecessor is computed. (b) read `routes_license.create_stage:201-235` (`overlapping` -> `to_void` -> `surviving` -> `highest`/`predecessor` -> voids at 232), `calc.stages_overlapping:251`, the successor lookups in `checkpoint_stage:340-344` and `compliance_sweep:332-340`, and the stage-closing helpers `routes_store._close_active_stage` / `close_selling` hop 2 / `revoke_license` hop 3 (which write `CLOSED`, never `VOIDED`, so they stay in the surviving set). (c) Dropped a first draft that also spelled out that checkpoint/licence-loss/sweep/closure stages "count too" (true, but already implied by the verbatim "have not been voided" and outside the fix), and softened "is still the predecessor" to "may therefore still be the predecessor" since the superseded stage is only the predecessor when it holds the highest index.
6. **§3.9** — (a) subject: the opening field values of a settlement worksheet. (b) read `routes_money._blank_settlement:215-236` (every computed field `None`, `dispute_round` 0), `create_settlement` (sole creation site), `calc.compute_settlement_split:510-566` (writes all of them at propose, including `guaranty_amount_cents` and the `retention_accrual_cents` disclosure line), `respond_settlement`, `finalize_settlement`, `serializers.settlement`. (c) Phrased as "every figure the proposal would compute" so it covers `guaranty_amount_cents` and `retention_accrual_cents` as well, and stated `dispute_round` at 0 explicitly so the new "each null rather than zero" clause cannot be read as sweeping the counter in with it.

**Not patched (PRD already determinative, or pure fixture bug):** `assert_inventory_lot` cost value (§3.2 already says "initial units less any returned units"); `assert_lease_disposition` and the `types.py` widening (§3.8 already says a `DRAFT` disposition opens "with every negotiated, computed, and allocation field unset"); `test_18` headers `AttributeError`; `test_14`'s identical-`created_at` setup (§3.6's `created_at`-then-`category` tie-break already pins it); `test_13`'s `== 0` -> `is None` (§3.7 already spends "0" and "unset" distinctly).

Orchestrator note: PRD_FINALIZED.md is 115,556 bytes vs PRD.md's 113,572 — not byte-identical, so the pass genuinely ran.

Orchestrator decision for Step 9: run it as THREE sequential passes partitioned by implementation module over one shared `PRD_COMPLETED.md`, because a single subagent cannot hold 3,700 lines of implementation plus a 476-line PRD and still scan exhaustively; a one-shot pass historically returns a byte-identical file. Pass 1 does the `cp` and owns the infrastructure modules; passes 2 and 3 must NOT re-copy, and each edits the file pass 1 created.

## Step 9: Complete PRD — 2026-09-04T16:15:00.000Z

Run as three sequential passes partitioned by implementation module over one shared `PRD_COMPLETED.md`. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 edited in place and were explicitly forbidden to re-copy.

### Pass 1 — infrastructure / cross-cutting (`app.py`, `response.py`, `shape.py`, `auth.py`, `helpers.py`, `errors.py`, `clock.py`, `money.py`, `db.py`, `serializers.py`)

PRD_FINALIZED.md 476 lines / 115,556 chars -> PRD_COMPLETED.md 476 lines / 121,958 chars (+6,402). 17 ambiguity-pins, 5 mismatch-revisions.

- §2.1 ¶1 — revise — mismatch — PRD demanded a mandatory `X-User-Role` header naming the role; impl never reads it and derives the role from `X-User-ID` alone; also pinned whitespace-only header = missing, and trimming — `auth.py:18-38`
- §2.1 ¶2 — insert — ambiguity — the four opaque prefixes are tested first and a match settles the role with no store lookup — `auth.py:32-37`
- §2.1 ¶3 — revise — mismatch — `StoreManager` was keyed on `X-User-Role`; impl resolves it as the fallback for an unprefixed id that matches a store — `auth.py:35-38`
- §2.2 bullet — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9` (24 total) — `response.py:10-14`
- §2.2 bullet — insert — ambiguity — `api_request_timestamp` reads the logical clock, not wall time, so it repeats across responses — `response.py:20`, `clock.py:65`
- §2.2 bullet — insert — ambiguity — key order never alphabetised (`meta`/`response_type`/`data`; ids before pagination), pagination keys absent on object responses — `app.py:25`, `response.py:28-50`
- §2.3 ¶1 — insert — ambiguity — non-integer `limit`/`offset` -> `ERR_INVALID_REQUEST`, empty value = absent -> default, `offset` unbounded above and past-the-end yields empty `data` with `has_more` false, bounds checked at step 6 before path resolution — `shape.py:149-167`, `routes_store.py:76-85`
- §2.3 ¶2 — insert — ambiguity — equal `created_at` (routine under a static logical clock) is tie-broken by insertion order, never by `id` — `db.py:78-83`
- §2.3 ¶2 — insert — ambiguity — empty filter = absent, out-of-enum filter -> `ERR_INVALID_REQUEST`, id-valued filters matched literally with no existence check (empty set, not 404) — `shape.py:170-183`, `routes_engagement.py:422-432`
- §2.4 ¶1 — insert — ambiguity — `id` is a v4 UUID in canonical lower-case hyphenated form — `db.py:38-39`
- §2.4 ¶1 — insert — ambiguity — `updated_at` equals `created_at` exactly on a fresh row — `db.py:45-47`
- §2.4 ¶1 — insert — ambiguity — every entity response carries exactly the fields §3 names, `id` first and `created_at`/`updated_at`/`version` last, unset fields present as null, no bookkeeping keys — `serializers.py:10-299`
- §2.4 ¶2 — insert — ambiguity — `current_utc` required with trailing `Z`, response `data` echoes the supplied string verbatim, and a supplied `X-User-ID` on the exempt clock endpoint is still resolved and role-checked — `routes_engagement.py:437-446`, `clock.py:41-51`
- §2.4 ¶3 — insert — ambiguity — instants render as `...SS.mmmZ` with sub-millisecond precision truncated, not rounded — `clock.py:58-62`
- §2.5 ¶1 — insert — ambiguity — ratios travel as JSON numbers with trailing zeros dropped (`0.85`, `0.0`), null when uncomputed, and client-supplied ratios are rounded half up to 4 dp on input rather than refused — `money.py:44-50`, `shape.py:87-99`
- §2.9 ¶1 — insert — ambiguity — a roll-up-only row still gets `updated_at` refreshed; only `version` is withheld — `db.py:64-69`, `routes_store.py:63-66`  *(later re-scoped by pass 3)*
- §2.10 — insert — ambiguity — unrouted path/method answers the error envelope with `ERR_INVALID_REQUEST` at the transport's 404/405, never an entity not-found; trailing slash equivalent — `app.py:24`, `app.py:38-44`
- §2.11 step 4 — revise — mismatch — strict step-4-before-step-8 only holds for a path store id; when scope can only be judged from a child row, a missing row yields the 404 instead — `auth.py:54-69`, `routes_store.py:91-96`
- §2.11 step 5 — revise — mismatch — self-approval check likewise defers to existence and passes when the recorded submitter is null — `auth.py:72-82`
- §2.11 step 6 — insert — ambiguity — percentage ranges inclusive at both ends — `shape.py:97`
- §2.11 step 6 — insert — ambiguity — absent/empty body = empty object, JSON parsed regardless of `Content-Type`, undeclared keys ignored, explicit `null` == absent (required->invalid, optional->default), int fields reject bools but accept integral floats, strings reject blank and are stored untrimmed, code lists must be arrays of known codes with order preserved — `shape.py:24-144`
- §4 preamble — revise — mismatch — `X-User-Role` described as carried-and-ignored rather than required — `auth.py:18-38`

Verified, no change needed: the §5 error catalogue matches `errors.py:3-83` id-for-id and status-for-status (including the deliberate 400s on `ERR_DUPLICATE_CLAIM_CODE`, `ERR_LICENSE_PERIOD_TOO_LONG`, `ERR_AUGMENTATION_SOURCE_FORBIDDEN` and the 412/422 sets); `helpers.py:8-21` not-found mapping matches §2.10; the 12 created-resource endpoints answering 201 matches §4 exactly; all twelve serializer field sets are covered by existing §3 prose.

### Pass 2 — `calc.py`, `routes_engagement.py`, `routes_store.py`

121,958 -> 129,628 chars (+7,670), still 476 lines. 23 ambiguity-pins, 3 mismatch-revisions.

- §3.1 jurisdictions — insert — ambiguity — `code` is 2-8 letters `A`-`Z` only (digits malformed -> `ERR_INVALID_REQUEST`), uniqueness checked after shape — routes_engagement.py:20,30,55
- §3.1 jurisdictions — insert — ambiguity — which five rule-set fields are required vs the four that default — routes_engagement.py:33-53
- §3.1 engagement draft — insert — ambiguity — inverted `sale_start_date`/`target_end_date` is step 6 `ERR_INVALID_REQUEST`, not `ERR_INVALID_DATE_RANGE` — routes_engagement.py:115
- §3.1 engagement draft — insert — ambiguity — all three rate fields optional; `guaranty_pct` null when omitted, the other two default to 0 — routes_engagement.py:101-112
- §3.1 store create — insert — ambiguity — store's three other derived ratios open at exactly 0.0000, not null — routes_engagement.py:391-396
- §3.1 submit-for-approval — insert — ambiguity — the recompute rewrites every store's derived figures but moves no store `version`/`updated_at` — routes_engagement.py:190
- §3.1 approval decision — insert — ambiguity — `decision_note` validated then discarded, never persisted — routes_engagement.py:202
- §3.1 wind-down — insert — ambiguity — same store-row `version`/`updated_at` reading as submission — routes_engagement.py:240
- §3.2 lot filing — insert — ambiguity — `ERR_AUGMENTATION_SOURCE_FORBIDDEN` fires inside step 6, after field checks, before the path store is resolved (pass-1 open item) — routes_store.py:32-37
- §2.11 step 6 — insert — ambiguity — same error named in the ordered list for `POST /stores/{id}/inventory-lots` (pass-1 open item) — routes_store.py:34
- §3.2 lot roll-up — insert — ambiguity — store's `updated_at` re-stamped, engagement's not; 201 body already carries computed `projected_recovery_cents` — routes_store.py:60-67
- §3.2 projected recovery — insert — ambiguity — a returned-to-supplier lot's own `projected_recovery_cents` is rewritten to 0 — calc.py:154-155
- §3.2 recompute triggers — revise — mismatch — list extended to posted days, store suspend/close, submit/approve/wind-down/sweep — routes_engagement.py:190,225,240,345; routes_store.py:393
- §3.2 recovery-summary — revise — ambiguity — engagement-level ratio denominators pinned, `planned_avg_discount_pct` is the pooled unweighted mean over all stores' ARMED/ACTIVE stages, and the read advances no `version`/`updated_at` — routes_engagement.py:249-282
- §3.3 sweep — insert — ambiguity — engagement must not be `CLOSED` (`ERR_ENGAGEMENT_STATE_INVALID`), no other gate — routes_engagement.py:289
- §3.3 sweep — revise — mismatch — an expiry whose store is not `SELLING` expires and counts but causes no suspension, stage closure or strike; licence pass completes before the stage pass — routes_engagement.py:300-317
- §3.3 sweep — insert — ambiguity — promotion stamps `activated_at`, answers to no licence/posture/single-active check, and a promoted successor whose window also ended is retired in the same pass, chaining onward — routes_engagement.py:319-340
- §3.3 sweep — insert — ambiguity — per-row `version` increments (licence, store, stage), engagement +1 even on a no-op sweep, `closed_stage_count` spans both passes — routes_engagement.py:302-346
- §3.3 discretionary suspension — insert — ambiguity — any of the four `suspension_reason` readings incl. `NONE` accepted and stored — routes_store.py:405-411
- §3.3 discretionary suspension — insert — ambiguity — store and closed stage versioned; engagement roll-up rewritten without `version`/`updated_at` — routes_store.py:418-423
- §3.6 sales-day filing — insert — ambiguity — unset `selling_start_date` fails the window outright; status is no gate except `CLOSED`/`SURRENDERED` — routes_store.py:114-123
- §3.6 sales-day filing — revise — mismatch — the `net_sales_cents` identity holds by construction (server-computed, client key ignored); only the augmentation-money fault is reachable — routes_store.py:131-143
- §3.6 allocation — insert — ambiguity — third tie-break after `created_at` and `category` is insertion order — calc.py:402
- §3.6 allocation — insert — ambiguity — `allocation_note` format `SOURCE:units@lot-id` joined by `;`, null when nothing allocated — calc.py:417,427
- §3.7 close-selling — insert — ambiguity — stages closed and employees settled/terminated each increment `version`; the auto payroll item stands at `version` 1 with shares written — routes_store.py:347,360,371-391
- §3.8 lease disposition create — insert — ambiguity — `daily_holdover_rate_cents` also >= 0; the disposition must be opened before the store closes (`ERR_STORE_STATE_INVALID`) though surrender requires a closed store — routes_store.py:254,264
- §2.11 step 10 — insert — ambiguity — child creation on a shut store draws `ERR_STORE_STATE_INVALID`, never `ERR_STORE_NOT_SELLING` — helpers.py:55-58

### Pass 3 — `routes_license.py`, `routes_money.py`, `routes_augmentation.py`, `routes_staffing.py` (+ the two pass-2 hand-offs and the cross-pass §2.9 tension)

129,628 -> 139,170 chars (+9,542), still 476 lines. 24 ambiguity-pins, 7 mismatch-revisions. Structure check: 5 `##`, 21 `###`, heading list byte-identical to `PRD_FINALIZED.md`; file still ends at the complete §5 error table (65 `ERR_*` rows, last `ERR_ECONOMICS_CONFIG_INVALID | 422`); §4 endpoint table still 61 rows. Verified by line diff against `PRD_FINALIZED.md` that every line pass 1 and pass 2 had changed still differs — nothing undone.

- §2.9 — revise — mismatch — pass 1's blanket "roll-up still refreshes `updated_at`" re-scoped: only the store on a lot filing gets that treatment; elsewhere a roll-up-only row keeps both fields, with the engagement's non-versioning paths enumerated — routes_store.py:66 (only `db.refresh` call in the codebase)
- §2.11 step 4 — insert — ambiguity — third scoping branch: a payload-carried `store_id` is scoped *after* step 6, and an omitted one leaves nothing to scope — routes_money.py:24-29
- §2.11 step 7 — revise — mismatch — stage window must be **strictly** earlier, so equal dates also draw `ERR_INVALID_DATE_RANGE` — routes_license.py:188
- §2.11 step 34 — revise — mismatch — settlement basis is judged *before* steps 32/33 on propose and finalize — routes_money.py:301-306, 345-354
- §3.3 — insert — ambiguity — licence filing gated on store openness alone (any engagement status, any posture, even where `gob_license_required` is false) — routes_license.py:32-34
- §3.3 — insert — ambiguity — **hand-off 1:** "most recent non-denied licence" = latest `period_end_date`, ties by insertion order (latest wins), negative gaps refused, no prior = pass — calc.py:292 / routes_license.py:48
- §3.3 — insert — ambiguity — `decision_reason` persisted verbatim (null when omitted) on denial as on approval — routes_license.py:113
- §3.3 — insert — ambiguity — approval leaves a store in any non-`LICENSE_PENDING` status wholly untouched; no roll-up on either decision — routes_license.py:122-125
- §3.3 — revise — mismatch — revocation: hops 2-5 and the strike are conditional on the store having been `SELLING`; engagement `version` advances on every revocation, store's only when suspended — routes_license.py:146-167
- §3.4 — insert — ambiguity — equal/inverted stage window -> `ERR_INVALID_DATE_RANGE` at step 7 — routes_license.py:188
- §3.4 — insert — ambiguity — `sell_through_target_pct` of 0 -> `ERR_INVALID_REQUEST`, not `ERR_STAGE_SEQUENCE_INVALID` — routes_license.py:180-181
- §3.4 — insert — ambiguity — `supersede_overlapping` only rescues an all-`ARMED` overlap set; an `ACTIVE` overlap still refuses and voids nothing — routes_license.py:206-208
- §3.4 — insert — ambiguity — authoring bumps store `version` by exactly 1 however many stages were voided; engagement keeps `version`/`updated_at` — routes_license.py:253-256
- §3.4 — insert — ambiguity — activation recomputes nothing; store and engagement untouched — routes_license.py:312-315
- §3.4 — insert — ambiguity — checkpoint bumps stage *and* store `version`; engagement untouched; no posture gate — routes_license.py:328-357
- §3.5 — insert — ambiguity — consignment `unit_retail_cents` below `unit_cost_cents` -> `ERR_INVALID_REQUEST` at step 6 — routes_augmentation.py:28-29
- §3.5 — insert — ambiguity — disclosure filing gated on consignment status alone (store status/posture ignored); only its own `version` moves — routes_augmentation.py:118-125
- §3.5 — insert — ambiguity — receipt: new lot at `version` 1, engagement keeps `version`/`updated_at` — routes_augmentation.py:189-193
- §3.5 — revise — mismatch — `units_returned` must be at least 1 (a declared 0 -> `ERR_INVALID_REQUEST`) — routes_augmentation.py:201
- §3.5 — insert — ambiguity — the declared return quantity is a ceiling only and is otherwise discarded; no partial return — routes_augmentation.py:217
- §3.5 — insert — ambiguity — return leaves engagement `version`/`updated_at` alone — routes_augmentation.py:232-236
- §3.6 — insert — ambiguity — `reject_reason` validated then discarded on either decision — routes_staffing.py:101
- §3.6 — insert — ambiguity — the store's status gates neither review decision; only licence coverage stands — routes_staffing.py:107-118
- §3.6 — insert — ambiguity — **hand-off 2:** posting also versions the sold-out consignment and leaves engagement `version`/`updated_at` alone (`allocation_note` null-on-empty was already pinned) — routes_staffing.py:129-136
- §3.7 — insert — ambiguity — employment action: store status/posture no gate; employee `version` +1; notice runs no recompute; termination rewrites accrual in place without versioning the engagement or touching the store — routes_staffing.py:42-68
- §3.7 — revise — mismatch — pay-bonus store gate (step 10) precedes eligibility (step 38), so `ERR_STORE_NOT_SELLING` wins — routes_staffing.py:77-83
- §3.7 — insert — ambiguity — pay-bonus versions only the employee; engagement accrual re-summed in place — routes_staffing.py:87-90
- §3.7 — insert — ambiguity — expense `store_id` resolved for existence only, against the whole store collection, so cross-engagement charges are accepted — routes_money.py:33-34
- §3.7 — insert — ambiguity — `decision_note` validated then discarded; `decided_by_user_id` recorded on a void too; both actions bump item *and* engagement `version` — routes_money.py:86-114
- §3.8 — insert — ambiguity — offer bumps the disposition's `version`; no other row, no roll-up — routes_money.py:141
- §3.8 — insert — ambiguity — an omitted counter amount is stored as null (overwriting a prior one); the field is ignored on `ACCEPT`/`REJECT` — routes_money.py:157-166
- §3.8 — revise — mismatch — reserve test (step 29) sits behind the notice period (step 24), so a premature under-reserve surrender reports `ERR_SURRENDER_NOTICE_SHORT` — routes_money.py:189-192
- §3.8 — insert — ambiguity — surrender runs no projection or engagement roll-up; engagement `version`/`updated_at` untouched — routes_money.py:206-209
- §3.9 — insert — ambiguity — propose bumps only the worksheet's `version`; no store/engagement recompute — routes_money.py:308-312
- §3.9 — insert — ambiguity — an `ACCEPT` leaves `dispute_reason`/`dispute_round` alone and ignores a supplied reason; either answer bumps only the worksheet — routes_money.py:331-337
- §3.9 — insert — ambiguity — each `APPROVED -> SETTLED` item's own `version` increments — routes_money.py:370-373

### Step 9 totals and orchestrator verification

64 ambiguity-pins + 15 mismatch-revisions = 79 edits across the three passes. `PRD_COMPLETED.md` is 476 lines / 139,170 chars against `PRD_FINALIZED.md`'s 476 / 115,556 — **+23,614 chars, 128 differing diff lines, so the scan genuinely ran and is nowhere near byte-identical**. Heading structure unchanged (5 `##`, 21 `###`); the file ends at the complete final error-table row. `ls -lt implementation/` shows the newest implementation file untouched since 15:17 (the Step 7 fix window), confirming all three Step 9 passes were documentation-only — the green 8-round sweep verified at Step 7 still describes the shipped implementation.

Pipeline complete.
