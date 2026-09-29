# Worklog — task_2193_chargemaster_maintenance_pricing_governance

## Step 1: Create task directory — 2026-08-31T17:54:29.395Z

Created `tasks/task_2193_chargemaster_maintenance_pricing_governance/` and `tasks/task_2193_chargemaster_maintenance_pricing_governance/workspace/` (pre-allocated name used verbatim; no index scan performed).

## Resume — 2026-08-31T18:37:30.539Z

Previous run crashed after Step 1. Verified on-disk state: only `worklog.md` and an empty `workspace/` existed. No SCAFFOLD*.yaml, PRD, tests, or implementation present. Pipeline resumed from Step 2 in the same task directory.

## Step 3: Copy shared files — 2026-08-31T18:37:30.539Z

Copied `./INSTRUCTION.md` → `tasks/task_2193_chargemaster_maintenance_pricing_governance/workspace/INSTRUCTION.md` (53 lines). Run out of order relative to Step 2 (which was concurrently in flight) since it has no dependency on the scaffold.

## Resume #2 — 2026-08-31T19:02:00.000Z

Previous run crashed again, this time during Step 2 (scaffold generation) — no scaffold artifacts were written. Verified on-disk state: `worklog.md` and `workspace/INSTRUCTION.md` (53 lines, byte-identical to project-root `INSTRUCTION.md`) are the only artifacts. Steps 1 and 3 confirmed valid; Steps 2, 4, 5, 6, 7, 8, 9 all pending. Pipeline resumed from Step 2 in the same task directory.

## Resume #3 — 2026-08-31T19:20:00.000Z

Previous run crashed a third time during Step 2. Re-verified on-disk state: `worklog.md` (17 lines) and `workspace/INSTRUCTION.md` (53 lines, `diff` clean against project-root `INSTRUCTION.md`) are the only artifacts; no `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `PRD.md`, `test_helpers/`, `test_suite/`, or `workspace/implementation/`. Steps 1 and 3 confirmed valid and NOT redone; pipeline resumed from Step 2 in the same task directory.

## Resume #4 — 2026-08-31T19:28:33.000Z

Previous run crashed a fourth time during Step 2. Re-verified on-disk state via `find`: only `worklog.md` and `workspace/INSTRUCTION.md` exist (53 lines, `diff` clean against project-root `INSTRUCTION.md`). No `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `workspace/PRD.md`, `test_helpers/`, `test_suite/`, `workspace/implementation/`, `PRD_FINALIZED.md`, or `PRD_COMPLETED.md`. Steps 1 and 3 confirmed valid and NOT redone; pipeline resumed from Step 2 in the same task directory.

## Resume #5 — 2026-08-31T19:40:10.000Z

Previous run crashed a fifth time during Step 2. Re-verified on-disk state via `find`: only `worklog.md` (25 lines) and `workspace/INSTRUCTION.md` exist; `diff` against project-root `INSTRUCTION.md` is clean. No `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `workspace/PRD.md`, `test_helpers/`, `test_suite/`, `workspace/implementation/`, `PRD_FINALIZED.md`, or `PRD_COMPLETED.md`. Steps 1 and 3 confirmed valid and NOT redone; pipeline resumed from Step 2 in the same task directory.

## Resume #7 — 2026-08-31T20:05:00.000Z

Previous run crashed a seventh time during Step 2. Re-verified on-disk state via `find`: only `worklog.md` and `workspace/INSTRUCTION.md` exist; `diff` against project-root `INSTRUCTION.md` is clean (53 lines). No `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `workspace/PRD.md`, `test_helpers/`, `test_suite/`, `workspace/implementation/`, `PRD_FINALIZED.md`, or `PRD_COMPLETED.md`. Steps 1 and 3 confirmed valid and NOT redone; pipeline resumed from Step 2 in the same task directory.

## Step 2a: Generate SCAFFOLD.yaml (§1.0–§1.7) — 2026-08-31T20:31:00.000Z

Attempts 1–7 of Step 2 all stalled with ZERO bytes persisted. Root cause: the 73KB SKILL.md plus an attempted single ~2000-line `Write` exceeded the stream watchdog window. Step 2 was therefore split into three sequential single-file agents, with mandatory sentinel-based incremental appends (~250 lines per call) so partial progress always persists. Attempt 8 succeeded.

Done. `SCAFFOLD.yaml` is complete (§1.0–§1.7 only) and lints clean.

**Contents**

- **Entities (14):** Facility, Department, RevenueCode, ChargeItem, PriceRule, ChangeRequest, CodeUpdateCycle, CodeUpdateEntry, PayerContract, ChargeCaptureBatch, CapturedCharge, MissingChargeFinding, PriceChangeImpactAnalysis, TransparencyFile.
- **State machines (10 entries = 1 derived + 9 transition machines, 46 transitions):** Facility.chargemaster_posture (derived, 3: OPEN/RESTRICTED/FROZEN), ChargeItem.lifecycle_status (6, 7 transitions), ChargeItem.price_status (4, 7) — parallel dimensions on one entity, ChangeRequest (8, 9), CodeUpdateCycle (6, 5), CodeUpdateEntry (5, 5), ChargeCaptureBatch (5, 5), MissingChargeFinding (4, 3), TransparencyFile (5, 5), PriceChangeImpactAnalysis (3, 2). No unreachable states in any machine.
- **Concurrency rules (2, §1.2.1):** `change-request-approve-stale-item` (parent ChargeItem, `POST /chargemaster/change-requests/{change_request_id}/approve`, `expected_charge_item_version`, ERR_STALE_ITEM_VERSION/412) and `transparency-build-stale-facility` (parent Facility, `POST /chargemaster/transparency-files`, `expected_facility_version`, ERR_STALE_FACILITY_VERSION/412). Both OCC fields verified present as required inputs on the named endpoints; no forbidden concurrency vocabulary anywhere in the file.
- **Calculations (9):** price_rule_selector, gross_charge_from_price_rule, markup_compliance_ratio, code_update_crosswalk_price_carry, payer_impact_delta (dual variant FORWARD_PROJECTED/HISTORICAL_REPLAY), duplicate_similarity_score (dual variant STRICT_CODE/FUZZY_DESCRIPTION), charge_capture_variance_summary, missing_charge_detection, transparency_file_build.
- **Validations:** 66 ordered rows, priorities 1–54 (auth 3, existence 7, schema-within-business categories: state 15, business_referential 9, business_temporal 7, business_constraint 18, business_safety 5, business_fiscal 2).
- **Endpoints:** 58 (28 GET), all under `/chargemaster` plus the test-driving `POST /_clock/set_current_utc` (fixed startup default `2026-08-01T00:00:00Z`). No duplicate method+path.
- **Errors:** 65 codes (401×1, 403×2, 404×8, 409×36, 412×2, 422×16).
- **Roles (6):** SystemAdmin, RevenueIntegrityAnalyst, PricingCommitteeApprover, ComplianceOfficer, ContractManager (all `identity: opaque`), DepartmentManager (`identity: entity_backed:Department`, X-User-ID vs Department.manager_user_id). Every role appears in at least one endpoint's `roles`, and no endpoint references an undeclared role.

**Verification**

- `wc -l` = **2165**; `yaml.safe_load` parses; top-level keys are exactly `api_prefix, calculations, complexity_profile, concurrency_rules, domain_name, endpoints, entities, errors, response_envelope, roles, scenario, state_machines, validations` — neither `scaffold_difficulty_design` nor `scaffold_corner_design` is present, and the `# ---APPEND-HERE---` sentinel is gone.
- Linter: `scaffold_lint.py` needs 3 files, so I ran it with empty §1.8/§1.9 stubs in /tmp: **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (58 endpoints, 14 entities recognized). Check (f) FK reverse-reachability passes with zero violations; the only "gap" is the expected 0 §1.8/§1.9 instances, which later agents supply.
- Extra cross-checks I ran: every `ERR_` id referenced anywhere in the document is catalogued and every catalogued id is referenced (0 orphans either way, `ERR_XXX` envelope placeholder correctly excluded); every §1.4 `http_status` matches its catalog entry (0 mismatches).

Orchestrator re-verification (independent): 2165 lines; `yaml.safe_load` OK; 14 entities / 58 endpoints / 65 errors / 66 validations / 9 calculations / 10 state_machines / 6 roles; neither design key present; sentinel count 0.

## Step 2b: Generate SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8) — 2026-08-31T21:20:00.000Z

The first single-agent attempt at all 9 rules stalled during its READING phase (600s watchdog, zero bytes written) — inputs were the 73KB SKILL.md plus the now-169KB SCAFFOLD.yaml, and it tried to plan all 18 instances before emitting anything. Step 2b was therefore re-partitioned into three concurrent fragment agents by rule family, each reading only SKILL.md lines 187–235 (§0.5 rules) and 562–675 (§1.8 spec) instead of the whole spec, each owning an exclusively-written fragment file, each required to land its first complete instance within 5 tool calls.

Fragment A (`dual_variant_calc`, `combinatorial_formula`, `boundary_precision_check`) — 1019 lines, 8 instances (2/3/3).
  - dual_variant_calc__payer_impact_forward_vs_historical_on_payer_contract_domain
  - dual_variant_calc__duplicate_similarity_strict_vs_fuzzy_on_charge_item_domain
  - combinatorial_formula__mode_a_tier_floor_cap_nesting_with_rounding_mode_applied_last
  - combinatorial_formula__mode_b_round_per_line_then_average_variance_rollup
  - combinatorial_formula__mode_c_exclusive_snapshot_evaluation_order_on_markup_ratio
  - boundary_precision_check__line_variance_bp_exactly_at_tolerance_100_on_reconcile
  - boundary_precision_check__included_item_count_zero_vs_one_on_transparency_validate
  - boundary_precision_check__similarity_score_exactly_at_0_8000_threshold_on_mark_duplicate
  NOTE: agent A terminated with an upstream API server error DURING its self-validation step, after the file was already complete (sentinel removed, YAML parsing, all rules ≥2 instances). No rewrite was needed; the orchestrator ran the cross-check validation on its behalf at merge time (result: clean).

Fragment B (`non_linear_state_machine`, `transitive_cascade`, `cross_entity_state_dependency`) — 1048 lines, 7 instances (2/2/3).
  - non_linear_state_machine__charge_item_parallel_dimensions_double_revision_loop — lifecycle DRAFT→PENDING_REVIEW→DRAFT→PENDING_REVIEW→APPROVED while price_status independently advances PRICE_STALE→PRICED_CURRENT mid-loop; asserts gross_charge_cents == 144000, item version == 6.
  - non_linear_state_machine__change_request_two_round_revision_cycle_then_reject_branch — UNDER_REVIEW→CHANGES_REQUESTED→SUBMITTED→UNDER_REVIEW twice with reviewed_by_user_id cleared and re-set by a different analyst each round; asserts 168000/216000/220000 and projected_markup_ratio_bp == 8462, CR version == 9.
  - transitive_cascade__implement_item_supersedes_file_clears_facility_voids_sibling_request — depth-4 cascade over 5 entities from ChangeRequest APPROVED→IMPLEMENTED; both OCC rules exercised.
  - transitive_cascade__price_rule_supersession_stales_five_items_restricts_facility — depth 3; 5 items needed because the boundary is >= 5, not > 4.
  - cross_entity_state_dependency: ChargeItem→RevenueCode (ERR_REVENUE_CODE_RETIRED from two different from-states); TransparencyFile→CodeUpdateCycle (ERR_TRANSPARENCY_BLACKOUT, then identical PUBLISH succeeds after cycle MAPPING→CANCELLED, asserting derivation rule 1 outranks rule 2); ChargeCaptureBatch→Department where the blocking state is itself DERIVED (capture_hold crosses 500000 → ERR_DEPARTMENT_CAPTURE_HOLD → RESOLVE → same CLOSE succeeds).
  Three real chain bugs found and fixed during setup-replay: (1) a line appended after FINALIZE when lines are only appendable while INGESTED, and RECONCILED→RECONCILING is not a declared transition — line now pre-seeded at +72h, outside the 24h companion_window_hours, with reconcile_pass_count 2→1 and matched_line_count 1→2; (2) `$.data[0].id` unquoted inside a YAML flow mapping is a parse error (3 captures quoted); (3) removed a non-schema `setup_note:` key.
  Deliberate judgement call flagged by the agent: where Facility.version increments are describable from two vantage points (TransparencyFile SUPERSEDED side-effect and implement-cascade link 3), it asserts `Facility.version > ${fac_v_before_implement}` rather than a literal, since single-increment-per-mutation is implied but not pinned by the scaffold. Item and request versions, which are unambiguous, are asserted as exact literals.

Fragment C (`priority_pair_validation_conflict`, `resource_temporal_overlap`, `compensating_invariant`) — 767 lines, 7 instances (2/3/2).
  - resource_temporal_overlap__price_rule_half_open_abut_legal_then_one_second_collision — HALF-OPEN [effective_from, effective_to); abutting rule accepted (201), one second earlier → ERR_PRICE_RULE_OVERLAP.
  - resource_temporal_overlap__payer_contract_closed_abut_collides_then_exact_notice_gap_buffer_violation — CLOSED interval + notice buffer; abut → ERR_CONTRACT_TERM_OVERLAP (opposite adjacency verdict from the half-open case), exactly 30 days → ERR_CONTRACT_TERM_BUFFER_VIOLATION, 31 days → 201.
  - resource_temporal_overlap__batch_window_aggregate_capacity_third_cover_on_single_day — AGGREGATE-CAPACITY per-calendar-day multiplicity ≤ 2 → ERR_BATCH_WINDOW_CAPACITY_EXCEEDED.
  - priority_pair_validation_conflict__state_facility_frozen_beats_constraint_price_frozen_and_fiscal_no_rule — one reprice trips state p14 + business_constraint p50 + business_fiscal p53; winner ERR_FACILITY_FROZEN, and a follow-up FAIL then surfaces ERR_NO_APPLICABLE_PRICE_RULE proving p53 was live-but-masked. Notes ERR_ITEM_PRICE_FROZEN is structurally unreachable as winner on this endpoint.
  - priority_pair_validation_conflict__constraint_price_not_current_beats_fiscal_markup_limit_on_item_approve — business_constraint p49 vs business_fiscal p54; winner ERR_ITEM_PRICE_NOT_CURRENT, then ERR_AGGREGATE_MARKUP_LIMIT after a reprice. Full ordered §1.4 walk confirmed no p1–p16 row masks either pair.
  - compensating_invariant__department_leakage_money_conserved_across_confirm_then_resolve — conserved money split: unresolved_finding_amount_cents + recovered_charge_cents == 512000 invariant across 2× CONFIRM and both compensating RESOLVEs; capture_hold flips true at 512000 >= 500000 and back to false.
  - compensating_invariant__facility_active_census_and_aggregate_gross_conserved_across_cycle_activate_then_rollback — conserved census pair (active_item_count, aggregate_gross_charge_cents): (2, 704000) → ACTIVATE → (1, 422400) → ROLL_BACK → (2, 704000).
  All formula-derived asserts computed as real Python against §1.3 (round_half_up, floor-then-cap, tier boundaries), not estimated: grosses 128000/240000/576000, markup ratios 32000/26286/24000/25143, crosswalk carry 422400, findings 256000 each, batch totals 1472000, mean variance 0 bp. One fix applied: bracketed JSONPaths needed quoting to stay valid YAML in flow mappings.

**MERGE (orchestrator).** `/tmp/prdbench_2193_merge_validate.py merge` concatenated the three fragments into `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, sorted into canonical §0.5 rule order, asserting: single top-level key per fragment, no duplicate/missing/unknown rule_id, every rule ≥2 instances, total ≥18. Result — all 9 rule_ids present, **22 instances total** (2/3/2/2/2/3/3/3/2).

**MERGE-TIME VALIDATION (orchestrator, run on behalf of the three fragment agents).** A resolver script checked, across all 22 instances: every `call:` resolves to a real §1.5 method+path (query strings stripped, since listing filters are declared in `input:`); every `${var}` in a payload / path / `as_user_id` / assert is bound by a `captures:` on an EARLIER step of the same instance; every `ERR_` id in an assert exists in §1.6; no assert left as an unevaluated `round(`/`ceil(`/`floor(` expression; no duplicate instance `name` across the whole index. Result: **instances checked: 22, PROBLEMS (0)**.
One validator false positive was found and fixed in the validator (not the data): `GET /chargemaster/missing-charge-findings?batch_id=...&status=OPEN` initially failed to resolve because the resolver did not strip the query string; the endpoint is declared at SCAFFOLD.yaml:1866 with `batch_id?` and `status?` among its `input:` filters, so the design instance was correct.

## Step 4: Generate PRD — 2026-08-31T21:25:00.000Z

Launched EARLY, concurrently with the still-running §1.8 fragment agents and §1.9 corner agent, because Step 4 reads ONLY SCAFFOLD.yaml (complete and verified byte-stable at 169042 bytes / 2165 lines) and both design indices are withheld from it by contract anyway. Orchestrator guarded against staleness by re-checking SCAFFOLD.yaml's size/line count afterwards — unchanged, so the PRD is not stale relative to any §1.5 priority-ladder reshaping (none of the design agents needed one).

Final validation complete. All checks pass; no further edits needed.

## Deliverable

`workspace/PRD.md` — **545 lines**, sentinel count `grep -c 'APPEND-HERE'` → **0**.

Built incrementally per the anti-stall protocol: 1 `Write` + 14 `Edit` calls, each section under ~250 lines, with `wc -l` checkpoints at 170 / 248 / 302 / 356 / 406 / 545. No giant tool call was attempted.

## PRD structure

- `# Chargemaster Governance API — Product Requirements Document`
- `## 1. Introduction` — failure modes, three design ideas (segregation of duties, explicit posture, conserved compensating actions), literal-arithmetic warning
- `## 2. Core System Requirements`
  - 2.1 Actors, Headers and Role-Based Access Control
  - 2.2 API Response Structure (byte-identical verbatim block)
  - 2.3 Pagination
  - 2.4 Resource Identity, Timestamps and Version Semantics
  - 2.5 The Logical Clock and Interval Conventions
  - 2.6 Money, Basis Points and Rounding Discipline
  - 2.7 Chargemaster Posture: The Facility-Wide Governance Gate
  - 2.8 Stale-Version Rejection
  - 2.9 Path Resolution and Validation Ordering (ordered list 1–54, all 66 rows)
  - 2.10 Segregation of Duties
  - 2.11 Cascade and Recomputation Discipline
- `## 3. Business Logic & Workflows` — 3.1 Standing Up a Facility, Its Departments and the Revenue-Code Table; 3.2 Price-Setting Methodology, Gross Charge and Markup Compliance; 3.3 Creating a Chargemaster Item and Walking It Into Service; 3.4 The Pricing Dimension: Repricing, Staleness and the Publication Freeze; 3.5 Department Change Requests; 3.6 Payer Contracts and the Impact of a Price Change on Reimbursement; 3.7 The Annual CPT/HCPCS Code Update Cycle; 3.8 Duplicate and Inactive Item Cleanup; 3.9 Charge Capture Reconciliation and Missing-Charge Detection; 3.10 Building and Publishing the Price Transparency File
- `## 4. Endpoint Definitions` — intro paragraph on 201-vs-200, then a 4-column table with all 58 endpoints
- `## 5. Error Code Catalogue` — 2-column table with all 65 error ids

No audit/coverage footer inside the file, per the skill.

## Coverage checks (all programmatic against SCAFFOLD.yaml)

| Check | Required | Present | Missing |
|---|---|---|---|
| Error codes (`ERR_` ids) | 65 | 65 | 0 |
| Endpoint paths | 58 | 58 | 0 |
| Roles | 6 | 6 | 0 |
| Entity field names | 143 | 143 | 0 |
| Endpoint input identifiers | 98 | 98 | 0 |
| State-machine state values | all | all | 0 |
| Transition action/enum tokens | 27 | 27 | 0 |

Roles verified: `SystemAdmin`, `RevenueIntegrityAnalyst`, `PricingCommitteeApprover`, `ComplianceOfficer`, `ContractManager`, `DepartmentManager`.

Note on counts: the scaffold's 9 declared `state_machines` with transition lists carry **48** transitions (7 + 7 + 9 + 5 + 5 + 5 + 3 + 5 + 2), plus the transition-free derived `Facility.chargemaster_posture` machine — slightly more than the 46 quoted in the Step 2a brief. All 48 are written out, each with its preconditions, error ids and side effects. (The 48 figure supersedes the 46 recorded in the Step 2a entry.)

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS.** 143 entity field names and 98 endpoint input identifiers required; every one appears verbatim inside backticks. 0 missing.

**Contract 2 — Rule Coverage: PASS.** All 54 validation priority ranks (66 rows, including the split ranks at 13, 39 and 41) are enumerated in order in §2.9 with condition, `error_id`, HTTP status and `applies_to` scope, and re-stated in-workflow in §3. Both OCC rules (`change-request-approve-stale-item` → `expected_charge_item_version` / `ERR_STALE_ITEM_VERSION` 412; `transparency-build-stale-facility` → `expected_facility_version` / `ERR_STALE_FACILITY_VERSION` 412) appear with write endpoint, OCC field and error. All 9 calculation formulas are given in natural-language arithmetic with rounding order and both variants where dual (`STRICT_CODE`/`FUZZY_DESCRIPTION` at threshold 0.8000 to 4dp; `FORWARD_PROJECTED`/`HISTORICAL_REPLAY`). All 48 transitions carry their preconditions and side effects. Sibling-branch symmetry given equal density for both `→ REPRICE_PENDING`, both `→ WITHDRAWN`, and `BUILDING → VALIDATED` vs `BUILDING → FAILED`. Field defaults (logical clock `2026-08-01T00:00:00Z`, `limit` 10, `offset` 0, `version` 1) stated. Conservation invariants for both compensating actions (code-cycle `ROLL_BACK` restoring facility aggregates from `pre_activation_*`; finding `RESOLVE` conserving department leakage totals) stated explicitly.

**Contract 3 — §3 Path Purity: PASS.** 1463 backtick tokens scanned in §3: 0 tokens begin with `/`, 0 combine method + path. One bare-uppercase token, `DELETE`, was flagged by the mechanical scan; it is the `CodeUpdateEntry.action` enum value (scaffold: `ADD | DELETE | REVISE | CROSSWALK`), not an HTTP method in endpoint-identifier position — the domain defines no HTTP DELETE endpoint at all — so it is a required Contract 1 token and not a violation. §3 refers to operations by state transition (`DRAFT → PENDING_REVIEW`), by role plus gerund ("the analyst's start-mapping action"), or by capability; the concrete method/path pairs live only in §2 and §4.

## Deliberate omissions

None of substance. The scaffold's `trigger` strings are written as literal `POST /chargemaster/...` + `action=` composites; those exact strings are not reproduced verbatim inside §3 because Contract 3 forbids it — the same information is carried by transition-name plus role-and-gerund phrasing in §3 and by the §4 endpoint table. `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml` and any `SCAFFOLD_DIFFICULTY_PART_*.yaml` were never opened, listed or grepped, and no sibling `task_*/` directory was touched.

Orchestrator re-verification (independent): 545 lines; sentinel 0; all 65 error ids, all 58 endpoint paths and all 6 role names found verbatim in PRD.md; SCAFFOLD.yaml unchanged at 2165 lines.

## Step 2c: Generate SCAFFOLD_CORNER_DESIGN.yaml (§1.9) — 2026-08-31T22:05:00.000Z

Run concurrently with the §1.8 fragment agents. Terminated once by an upstream API server error mid-append at 6786 lines, but its on-disk work survived and parsed; the orchestrator diagnosed the truncation mechanically (endpoints section had only 7 instances, errors only 3; 14 error ids and 9 endpoint paths referenced nowhere) and RESUMED THE SAME AGENT from its transcript rather than regenerating, additionally supplying the 22 now-final §1.8 instance names so any `excluded_because:` stub could cite a real instance (the corner agent is forbidden from reading the §1.8 file, so unaided stub citations would have been guesses).

§1.9 corner design is complete and clean.

**File**: `SCAFFOLD_CORNER_DESIGN.yaml` — 9140 lines, single top-level key `scaffold_corner_design`, sentinel count 0.

**Per-section instance counts (96 total, 93 real + 3 stubs)**
- entities 13 (13 real)
- state_machines 22 (22)
- calculations 18 (18)
- validations 12 (12)
- endpoints 8 (8) — added E8 `every_governance_list_endpoint_filters_by_scope_status_and_pagination_window` covering the five remaining collection GETs (change-requests, code-update-cycles, code-update-entries, charge-capture-batches, transparency-files) plus captured-charges/missing-charge-findings, with AND-composed filters, `total_count` vs page semantics and an empty-but-200 filtered set
- errors 9 (9)
- rbac 6 (6): all six roles' exclusive ops end-to-end; pairwise cross-role denials (`ERR_ROLE_NOT_PERMITTED` fires before state/constraint checks); DepartmentManager peer-scope (`ERR_DEPARTMENT_SCOPE_VIOLATION`) vs `ERR_UNAUTHENTICATED`; two-step approval chain (`ERR_REQUEST_NOT_REVIEWED` then `ERR_SEGREGATION_OF_DUTIES` with a dual-role user that succeeds on a request it did not review); crosswalk mapper barred from `APPROVE_CROSSWALK` on the cycle it mapped; shared reads for every role
- cross_cutting_complexity_layers 6 (3 real + 3 stubs): real = OCC token monotonicity across all three OCC surfaces (both §1.2.1 rules + facility PATCH), facility derived-counter reconciliation after create/update/source-retirement, offset pagination across an append and a filtered-set removal; stubs cite `transitive_cascade__implement_item_supersedes_file_clears_facility_voids_sibling_request`, `dual_variant_calc__payer_impact_forward_vs_historical_on_payer_contract_domain`, `transitive_cascade__price_rule_supersession_stales_five_items_restricts_facility`
- consistency_model 2 (2): same-request visibility of cross-entity derived state (FROZEN posture enforced on the very next call) and atomicity of a rejected write (no counter/version movement, identical call succeeds after the limit is raised)

**Coverage**: errors 65/65 (`ERR_XXX` in SCAFFOLD.yaml is a template placeholder, not a real id); endpoints 58/58 method+path rows; 9/9 §1.3 calculations; 54/54 §1.4 priority rows now cited in `grounds`; all §1.2 state machines and their rejection edges.

**Validation status**
- `yaml.safe_load` → `['scaffold_corner_design']`; `grep -c APPEND-HERE` → 0
- every `call:` resolves to a real §1.5 method+path; all 52 `endpoints[...]` grounds refs resolve (fixed a bogus `price-change-impact-analyses` → `price-change-analyses`)
- every `${var}` bound by an earlier `captures:` (0 unbound); no `round(`/`ceil(`/`floor(` in any `assert` (one remains inside explanatory prose alongside its computed literal)
- `scaffold_lint.py SCAFFOLD.yaml <empty /tmp §1.8 stub> SCAFFOLD_CORNER_DESIGN.yaml` → **clean lint**, 93 instances / 1569 calls scanned, 0 violations (temp stub deleted). Fixes applied to reach clean: 3 change-request creates re-roled to `DepartmentManager`/`mgr_cath`, payer-contract payloads corrected to `payer_code`/`reimbursement_method`/`renegotiation_notice_days`, literal `expected_charge_item_version: 99` replaced with a captured stale token (`${v_priced}`), and capture paths corrected to the declared field names `chargemaster_posture`, `active_item_count`, `capture_hold`.

SCAFFOLD.yaml was not modified; the concurrent §1.8 file was never read or touched.

**JOINT §1.8 + §1.9 VALIDATION (orchestrator).** Ran the merge-validator across BOTH design files together: **instances checked: 118, PROBLEMS (0)**. Checks: no duplicate instance `name` across the union of §1.8 and §1.9; every `call:` resolves to a real §1.5 method+path; every `${var}` bound by an earlier `captures:`; every asserted `ERR_` id exists in §1.6; no assert left as an unevaluated formula; and every `excluded_because.difficulty_instance` resolves to a real §1.8 instance name (the one cross-file reference neither design agent could verify alone — all 3 stubs resolve).
Final artifact sizes: SCAFFOLD.yaml 2165 lines (169042 bytes, unchanged since Step 2a), SCAFFOLD_DIFFICULTY_DESIGN.yaml 4872, SCAFFOLD_CORNER_DESIGN.yaml 9140, workspace/PRD.md 545.

## Step 6: Generate implementation — 2026-08-31T23:05:00.000Z

Launched CONCURRENTLY with Step 5 in a single assistant message, so `test_suite/` and `test_helpers/` did not exist when this agent started — physical isolation, not merely instructed isolation. This agent was additionally barred from reading either design index.

Implementation complete and verified. Everything lives in `workspace/implementation/`.

## Modules (4104 lines of Python, plus `start.sh` + `requirements.txt`)

| file | lines | contents |
|---|---|---|
`calc.py` | 570 | all 9 calculations incl. both dual-variant ones (gross charge from price rule, markup compliance ratio, reprice selector, duplicate similarity, contract impact / forward-projected vs trailing-actual, capture variance summary, missing-charge detection, crosswalk price carry, transparency build + SHA-256 hash)
`routes_items.py` | 457 | charge items, both state dimensions, reprice, duplicate candidates, archive→entry-defer cascade
`routes_requests.py` | 454 | change requests, decisions, approve (OCC), resubmit, implement, price-change analyses interplay
`routes_code_update.py` | 426 | code-update cycles, entries, disposition (MAP/DEFER), cycle lifecycle with apply/revert
`routes_capture.py` | 402 | capture batches, lines, reconcile, batch lifecycle, captured charges, missing-charge findings + disposition
`routes_contracts.py` | 252 | payer contracts, contract lifecycle, impact analyses, sign-off
`routes_facilities.py` | 246 | facilities (POST/GET/PATCH), departments, revenue codes + retire
`derive.py` | 246 | posture derivation, `item_mutation_cascade` (§2.11), all counter/aggregate recomputes, staleness propagation
`validate.py` | 223 | schema/enum/int/datetime/id/pagination primitives (rank 11 / 12)
`routes_transparency.py` | 181 | transparency files, VALIDATE/PUBLISH/FAIL, freeze & thaw
`routes_pricing.py` | 157 | price rules + supersession
`store.py` | 131 | in-memory dicts, logical clock, stamping, serialization (strips `_`-prefixed internals)
`errors.py` | 97 | the 65-code catalogue with HTTP statuses
`envelope.py` | 91 | §2.2 envelope, list/meta, error shape
`auth.py` | 82 | 6 roles, rank-1/2/3 checks, DepartmentManager scope
`app.py` | 64 | blueprint registration, 404/405/unhandled mapped into the envelope
`routes_clock.py` | 25 | `POST /_clock/set_current_utc` + contract expiry sweep

Storage is pure in-memory dicts; no file, SQLite, or /tmp persistence anywhere. Zero seeded rows — the only startup state is the logical clock default `2026-08-01T00:00:00Z`. `Flask(__name__, static_folder=None)` so no undeclared `/static/...` route exists.

## Verification

- `python3 -m compileall -q .` clean; `grep -rn APPEND-HERE` → none.
- **Endpoints: declared 58 / registered 58, MISSING [] , EXTRA []** (method+path pairs extracted from SCAFFOLD §1.5 and compared against `app.url_map`).
- **Error codes: 65/65** present with the PRD §5 statuses; no status mismatches, and every code is actually raised somewhere outside `errors.py`.
- Smoke test (`PORT=18293 bash start.sh`), envelope exactly as PRD §2.2:
  - `POST /chargemaster/facilities` → 201 `{"meta":{"api_request_id":"req_b11325379d0a457c84bf61e1ecb51684","api_request_timestamp":"2026-08-31T22:55:25.237Z"},"response_type":"object","data":{...,"chargemaster_posture":"OPEN","created_at":"2026-08-01T00:00:00.000Z","transparency_status":"NEEDS_REFRESH","version":1,...}}`
  - `GET /chargemaster/departments` → `{"data":[],"meta":{...,"has_more":false,"limit":10,"offset":0,"total_count":0},"response_type":"array"}`
  - Error shape: `{"data":{"error_id":"ERR_FACILITY_NOT_FOUND","message":"Facility nope does not exist."},"meta":{...},"response_type":"error"}` at 404.
- **Fresh-boot empty-state proof** (separate port, brand-new process): `revenue-codes, departments, charge-items, price-rules, change-requests, code-update-cycles, charge-capture-batches, missing-charge-findings, transparency-files, payer-contracts, price-change-analyses, captured-charges, code-update-entries` → all `total_count: 0`.
- **Full end-to-end runtime exercise** (39 calls, all expected statuses, zero tracebacks in the server log): revenue code → department → price rule → item → reprice → SUBMIT/APPROVE/ACTIVATE → change request → REVIEW → impact analysis → approve (OCC pin) → implement (analysis correctly flipped to `STALE`) → code-update cycle → entry → START_MAPPING → MAP → APPROVE_CROSSWALK → ACTIVATE → ROLL_BACK (facility `active_item_count`/`aggregate_gross_charge_cents` restored exactly to the `pre_activation_*` snapshots: 1/44000 both sides) → capture batch → line → reconcile → FINALIZE → CLOSE → payer contract → transparency file build → VALIDATE → PUBLISH (facility `transparency_status` → `CURRENT`, frozen items thawed) → clock advance.
- Ordering spot checks at runtime: unknown role → `ERR_UNAUTHENTICATED` 401; role rejection before dept scope → `ERR_ROLE_NOT_PERMITTED` 403; dept scope before body-FK existence → `ERR_DEPARTMENT_SCOPE_VIOLATION` 403 (and `ERR_REFERENCED_RESOURCE_NOT_FOUND` 404 once scope passes); `limit=0` → `ERR_VALIDATION` 422. All smoke servers have been killed; ports free.

## Judgement calls (PRD ambiguities resolved) — PRIMARY INPUT TO STEP 8

1. `supersede_rule_id` not found → `ERR_REFERENCED_RESOURCE_NOT_FOUND` (rank 10); rank 9's `price_rule_id` clause is path-scoped.
2. `change_request_id` on `POST /price-change-analyses` → rank 10, not rank 6 (path-scoped).
3. "`code_value` may be null only when `code_type` is `REV_ONLY`/`CDM_INTERNAL`" enforced at rank 11 as `ERR_VALIDATION`.
4. `Facility.version` bumped unconditionally at the pinned call sites rather than §2.7's conditional reading.
5. §2.11 "fires identically no matter which operation triggers it" → ACTIVATE and REACTIVATE also run the full supersession cascade.
6. ARCHIVE preconditions follow §2.9 ranks (45 `ERR_ITEM_IN_OPEN_BATCH` before 46 `ERR_ITEM_HAS_OPEN_REQUEST`), not §3.3 prose order.
7. REACTIVATE follows ranks 25 → 49 → 51, not §3.3 prose order.
8. Action-level RBAC (rank 2) is skipped when `action` is absent or not a legal enum member, so rank 11 `ERR_VALIDATION` can surface.
9. Contract notice buffer evaluated against the single latest prior term of the scope key.
10. Analysis sign-off: `SIGNED_OFF` → `ERR_INVALID_ANALYSIS_STATE`; `STALE` or version drift → `ERR_ANALYSIS_SIGNOFF_STALE`.
11. Query-string `facility_id` filters do not trigger rank-4 existence (§2.9 says "in a path or body").
12. `api_request_timestamp` uses the real wall clock; `created_at`/`updated_at` use the logical clock.
13. Deterministic list ordering is `(created_at, insertion sequence)`; `_`-prefixed internal keys stripped on serialization.
14. Revenue-code retire is idempotent.
15. `duplicate-candidates` returns pure `ChargeItem[]` with no added score field (`min_score` filters only).
16. **Approve precedence conflict**: §3.5 prose and SCAFFOLD put OCC before the `RESTRICTED` posture check, but §2.9 ranks RESTRICTED 15 before OCC 16 — chose the §2.9 rank order (RESTRICTED → OCC → SoD → not-reviewed → mapping → markup).
17. Approve's markup gate recomputes the ratio fresh from the stored `projected_gross_charge_cents` without re-running the rule selector or writing the projection back.
18. `new_revenue_code_id` is absent from the rank-10 body-FK list, so entry creation does not existence-check it; a bad value surfaces at MAP as `ERR_REVENUE_CODE_MAPPING_INVALID`.
19. At MAP, revenue-code existence/ACTIVE is checked before crosswalk target resolution (rank 23 < 28) but `allowed_code_types` after, since it needs the resolved target's `code_type`.
20. Code-update entry creation requires only `action` (the scaffold marks the other three optional), so no cross-field requirement is enforced there.
21. MAPPED entries whose target is null (ADD) or ARCHIVED are skipped by ACTIVATE and stay MAPPED; ROLL_BACK reverts every APPLIED entry.
22. Batch ingestion evaluates `ERR_BATCH_WINDOW_CAPACITY_EXCEEDED` (rank 37) before `ERR_DEPARTMENT_CAPTURE_HOLD` (rank 47), reversing §3.9's prose order — same reasoning as #16.
23. Cascades that recompute counters which cannot have changed use no version bump (archive→defer, CLOSE's department recompute, post-reconcile batch recompute) to avoid gratuitous `version` increments.
24. VALIDATE re-runs `transparency_file_build` against the file's stored `as_of_datetime`, not the current logical now.

NOTE for Step 8: items 16 and 22 are INTERNAL PRD inconsistencies (§2.9's explicit rank table vs §3.5/§3.9 prose ordering), not scaffold-vs-PRD divergences. The agent resolved both in favour of §2.9, which is the section whose stated purpose is to define ordering. Step 8/9 should align the §3.x prose to §2.9 rather than the reverse.

Orchestrator re-verification (independent): 17 .py modules + start.sh + requirements.txt present; `python3 -m compileall -q .` clean; grep for `sqlite3|shelve|pickle.dump|json.dump(open|open(...,'w')` across implementation/ → no on-disk persistence; no `APPEND-HERE` sentinels remain.

## Step 5: Generate unit tests — 2026-09-01T00:10:00.000Z

Launched CONCURRENTLY with Step 6 in a single assistant message. Isolation held: no read, list, or grep of `workspace/implementation/` or any sibling `task_*/` directory.

Stage 2 is complete.

## Deliverables

**`test_helpers/`** (Stage 1, 2,590 lines): `__init__.py` 20, `api_client.py` 239, `api_errors.py` 142, `assertions.py` 287, `constants.py` 54, `factories.py` 172, `fixtures.py` 427, `scenarios.py` 834, `test_users.py` 68, `types.py` 347.

**`test_suite/`**: 77 test modules + `conftest.py`, 11,140 lines, **137 test functions**. Files run `test_10_*` … `test_86_*`, one domain per file (largest 152 lines).

## Coverage — 115/115 translatable instances, zero skips

- **Queue A (Difficulty): 22/22.**
- **Queue B (Corner): 93/93** — entities 13, state_machines 22, calculations 18, validations 9, endpoints 8, errors 9, rbac 6, cross_cutting_complexity_layers 3, consistency_model 2.
- The 3 `excluded_because` stubs were not emitted (audit confirms no stub tag appears).
- 137 tests / 115 unique tags: 22 large instances are split across two focused tests each (per-test-server isolation makes single 300-line tests fragile); every test carries exactly one `Design:` line as the last docstring line.

## Validation output

- `grep -rc 'APPEND-HERE' test_suite` → no non-zero file.
- `python3 -m compileall -q test_suite test_helpers` → clean.
- Coverage audit: `tags 137 / unique 115`, `A 22/22`, `B 93/93`, `UNRESOLVABLE: []`, `stub tags emitted: []`, `MISSING A/B: none`.
- Per-test tag audit: 137 functions, `problems: []` (no untagged, dual-tagged, or non-terminal tag).
- Citation audit (verbatim substring match against PRD.md): `problems: 0`.
- `grep -rn "pytest.mark.skip\|xfail" test_suite` → no matches.
- Static import audit: every name imported from `test_helpers`, every `api_client.*` method and every `factories.*` function used by the suite exists.

## Instances skipped — none. Partial omissions inside otherwise-emitted instances (recorded)

1. `Corner/errors/activation_rejected_while_a_crosswalk_is_pending...` — the design's closing step (second item `ACTIVATE` → `ERR_ITEM_PRICE_NOT_CURRENT`) omitted: §3.3 `APPROVED → ACTIVE` declares only three preconditions (revenue code ACTIVE, `effective_from`, pending code update) and the error table scopes `ERR_ITEM_PRICE_NOT_CURRENT` to `APPROVE`/`REACTIVATE`, so the PRD would let that call succeed.
2. Earlier: no `GET /chargemaster/facilities` collection assertion (endpoint not in §4), no literal `content_hash` value (only 64-hex-digit shape), and no duplicate-report score field name (PRD names the ranking, not the field).

## Design assertions corrected to the PRD (design-vs-PRD conflicts, all resolved toward the PRD)

- `rbac/approval_chain_...`: approving a still-`SUBMITTED` request asserted as `ERR_INVALID_REQUEST_STATE` 409 (§3.5 state gate precedes the review check), and SoD asserted at 409 (§2.9 rank 18), not the design's `ERR_REQUEST_NOT_REVIEWED`/403. Two sibling requests placed on two items so each approval's post-bump pin is unambiguous.
- `rbac/crosswalk_approval_...`: SoD asserted 409 not 403; the design's second cycle held only a `DEFERRED` entry, which §3.7 makes unapprovable (`ERR_CYCLE_HAS_NO_MAPPED_ENTRIES`), so that cycle was given a `MAPPED` entry dispositioned by a third analyst — preserving the claim that the bar is per-cycle.
- `rbac/each_role_...`: change-request approval routed through `POST /change-requests/{id}/approve` with `expected_charge_item_version` (§4), asserting `UNDER_REVIEW` after `REVIEW` rather than the design's "REVIEWED".
- `consistency_model/a_rejected_write_...`: `ERR_AGGREGATE_MARKUP_LIMIT` asserted 422 (§3.2/§3.3), not the design's 409.
- `consistency_model/every_write_response_...`: an ACTIVE payer contract was added, because §3.10 fails validation when `payer_column_count` is 0 — without it the file would go `FAILED`, not `VALIDATED`.
- `cross_cutting/version_tokens_...` and `.../facility_derived_counters_...`: hard-coded facility version literals (`fv2 == 2`) replaced with live-read relative assertions, since item activation already advances `Facility.version`.
- `errors/finding_disposition_...`: the design's recovery line would have tripped `ERR_RECOVERY_LINE_INVALID`; a genuine same-batch companion line was added so the asserted `ERR_INVALID_FINDING_STATE` / `ERR_INVALID_BATCH_STATE` are the uniquely derived outcomes.

Orchestrator re-verification (independent): 77 test files; 137 test functions; 137 `Design:` tags / 115 unique; A 22/22 and B 93/93 with `unresolvable tags: []`, `stub tags wrongly emitted: []`, `missing A: []`, `missing B: []`; `mark.skip|xfail` occurrences: 0; `compileall` clean.

## Step 7: Run tests and iterate — 2026-09-01T01:05:00.000Z

All 8 rounds are green. Final sweep: **137/137 in every round**.

## Summary

**Iterations run: 3 full 8-round parallel sweeps**
- iter 1: 124/137 (rounds 1,2,3,5,7,8), 125/137 (rounds 4,6) — 13 unique failing tests in the union
- iter 2: 136/137 in all 8 rounds — 1 unique failure
- iter 3: **137/137 in all 8 rounds**

### Tests/assertions deleted (PRD-silence category)
- `test_suite/test_55_validation_order_auth_and_existence.py` — deleted the `ERR_REQUEST_NOT_REVIEWED` assertion only (STEP 1c partial-coverage split; kept the covered `ERR_STALE_ITEM_VERSION` assertion). Category: **ERROR PRECEDENCE SILENCE / unreachable state** — §2.9 ranks entity-state admissibility (13) above OCC (16) and §3.5 puts OCC "after the generic state admissibility check", so a `SUBMITTED` request can only ever answer `ERR_INVALID_REQUEST_STATE`; `reviewed_by_user_id` is null only in `SUBMITTED`, making the not-reviewed branch unreachable. No other test asserted it.
- No whole test function or file was deleted.

### Fixes to `test_helpers/`
- `test_helpers/fixtures.py` → fixture `create_batch`: pop `facility_id`/`department_id` out of `**overrides` before passing them positionally to the factory — the helper passed `department_id` twice, so every test overriding the department died with a `TypeError` before touching the API (fixed test_67).

### Fixes to `test_suite/` (test-layer faults, STEP 2)
- `test_25` `_new_rule_payload` — merged hardcoded `flat_fee_cents` into an overridable dict (duplicate-kwarg `TypeError`).
- `test_57` `contract_body` — same collision on `percent_of_charge_bp` (the iter-2 residual failure).
- `test_46`, `test_58` — item `effective_from` predated each test's own logical clock; moved to 2026-09-30 / 2026-09-15 (§3.3 forbids back-dated `effective_from`).
- `test_55` — review the request before probing the stale OCC token (§2.9 rank 13 < 16).
- `test_56` — reframed the mapping probe to `code_type="CPT"` vs `allowed_code_types=["HCPCS"]`; the original probe (HCPCS + null `code_value`) sits in the genuinely ambiguous gap between rank 11 `ERR_VALIDATION` and rank 23 `ERR_REVENUE_CODE_MAPPING_INVALID`. Ordering intent (mapping before department whitelist) is preserved.
- `test_57` — create the contract, then move the clock past `term_end_date`; §2.5 makes `EXPIRED` a clock-*movement* cascade, so a back-dated contract legitimately starts `ACTIVE`.
- `test_59` — added a `PayerContract` to setup; without one `payer_column_count == 0` and §3.10 forces `VALIDATE` to `FAILED`.
- `test_62` — SoD probe now uses `make_approver_headers(ANALYST_USER_ID)`; `APPROVE_CROSSWALK` is a `PricingCommitteeApprover` action (§3.7), so analyst headers correctly yielded `ERR_ROLE_NOT_PERMITTED`.
- `test_63` — `REACTIVATE` probe now uses `APPROVER`; §3.3 declares reactivation a `PricingCommitteeApprover` action.

### Fixes to `workspace/implementation/`
- `routes_items.py` → `charge_item_lifecycle`: call `stale_analyses_for_item(item["id"])` after the mutation. §3.6: "`COMPUTED → STALE` fires whenever the target item is mutated" — it was only wired into `reprice_charge_item`.
- `routes_requests.py` → `implement_change_request`: the `price_status != REPRICE_PENDING` check now precedes the `status != APPROVED` check. §2.9 rank 13 declares the nine state rules "mutually exclusive… distinguished by target entity" and names `ERR_INVALID_ITEM_PRICE_STATE` as the rule "for change-request implementation" (reinforced verbatim in §3.4).

### Note on the one flake
`test_72` failed in 6/8 rounds of iter 1 with `ConnectionResetError(104)`, never with an assertion error. It was not reproducible in isolation, nor under a dedicated 8×-concurrent subset sweep (8/8), nor in iters 2 and 3 (16/16 green). The box is shared with other agents running their own dev servers, so this was infrastructure contention against the single-threaded Werkzeug server, not a PRD or code defect — no change was made for it.

Storage remains in-memory only (`store.py` `reset()` builds 14 empty dicts, no seeding, no disk/SQLite/`/tmp` persistence), and no endpoint, field, or capability was added to the implementation.

Orchestrator re-verification (independent): all 8 `results.{1..8}.json` parsed — every round `passed=137 total=137 failed=0`; `mark.skip|xfail` occurrences across test_suite/: 0; test function count still 137 (consistent with "no whole test deleted", only one assertion removed); no on-disk persistence in implementation/.

## Step 8: Finalize PRD — align documentation to implementation — 2026-09-01T01:20:00.000Z

Done. Three edit sites (four changed lines), all traced to `<step_7_diff>` items.

## Line counts
- `PRD.md`: 545 lines · `PRD_FINALIZED.md`: 545 lines · **0.0% line delta**; 4 lines revised (0.73% of lines), 0 inserted, 0 deleted, no new sections.

## Changes
- **§2.1 (role admission)** — *revise* — pinned that action-bearing endpoints whose §4 role list spans several roles also admit the *named action* at the role-admission rank: the acting role must own the named `action`/`decision`, otherwise `ERR_ROLE_NOT_PERMITTED`, evaluated ahead of scope, path resolution and the remaining schema checks; an unrecognized action falls through to `ERR_VALIDATION` — `routes_items.py:324-329`, `routes_code_update.py:182-187`, `routes_capture.py:219-224`, `routes_requests.py:154-159`.
- **§3.5 (request-changes)** — *revise* — "the reviewer of record" → "the reviewing `RevenueIntegrityAnalyst` of record", so the §2.1 rule is determinate for `REQUEST_CHANGES` — `routes_requests.py:30`.
- **§3.3 (item creation payload)** — *revise* — a null `code_value` under `code_type` `CPT`/`HCPCS` is a rank-11 `ERR_VALIDATION`, not the rank-23 mapping error, and precedes the posture gates — `routes_items.py:168-169`.
- **§3.5 (implementation)** — *revise* — the `PRICE_CHANGE`/`NEW_ITEM` `REPRICE_PENDING` check (`ERR_INVALID_ITEM_PRICE_STATE`) is evaluated **before** the request's own `APPROVED` state check — `routes_requests.py:373-383`.

## Per-edit pre-edit search log
1. **§2.1 per-action role admission.** (a) Subject: role admission on multi-role action endpoints. (b) Enumerated/read: `auth.py:require`, all four per-action gates (`routes_items.charge_item_lifecycle` LIFECYCLE_ACTIONS ×8, `routes_code_update.cycle_lifecycle` CYCLE_ACTIONS ×5, `routes_requests.decide_change_request` DECISIONS ×4, `routes_capture.batch_lifecycle` BATCH_ACTIONS ×3), plus multi-role endpoints *without* action dispatch (`create_analysis` CM+RIA with `variant`, all GET readers) and single-role action endpoints (`disposition_finding`, `transparency_file_lifecycle`); grepped every `ERR_ROLE_NOT_PERMITTED` site. (c) Adjustment: scoped the sentence to payloads naming an `action`/`decision` so `variant`-bearing and read endpoints are untouched; said "the rest of the payload's schema checks" rather than "all schema checks" because `validate.body()`'s JSON-object check precedes the role gate; verified §3 already names an owner for all 20 actions except `REQUEST_CHANGES`, which drove the companion §3.5 wording change.
2. **§3.3 `code_value`.** (a) Subject: `code_value` nullability rule, its error code and rank. (b) Enumerated: `routes_items.create_charge_item:166-177` (rank-11 check then posture then `check_mapping`), `mapping_legal`/`check_mapping` (also called from `SUBMIT_FOR_REVIEW`), `approve_change_request` remap mapping check, `entry_disposition` MAP mapping check, `_apply_entries`/`_revert_entries` which write `code_value` by cascade; grepped all `code_value` uses. (c) Adjustment: scoped to "a creation payload" so the cascade writers and the still-verbatim `requires_hcpcs` mapping rule (which retains its non-null `code_value` clause) are not contradicted; avoided any universal claim that a `CPT` item's `code_value` is always non-null.
3. **§3.5 implementation ordering.** (a) Subject: rank-13 state checks at the implement endpoint. (b) Enumerated: full check sequence in `implement_change_request:366-399` (price-state → request-state → `DEACTIVATION` lifecycle → FROZEN → pin → open batch), `routes_requests.py:449 _other_approved`, §3.4's existing statement of the same rule, and the only other `ERR_INVALID_ITEM_PRICE_STATE` site (grep: none outside implement). (c) Adjustment: dropped an earlier draft phrasing that called it "the rank-13 rule" for implementation (which would have implied exclusivity and mis-described the later `DEACTIVATION` → `ERR_INVALID_ITEM_LIFECYCLE_STATE` branch); final wording asserts only the price-state-before-request-state ordering and is explicitly conditioned on `PRICE_CHANGE`/`NEW_ITEM`, leaving the `REVENUE_CODE_REMAP`/`DEACTIVATION` paths unconstrained.

## Items deliberately left unpatched (PRD already determines, or test-only fault)
`test_55` `ERR_REQUEST_NOT_REVIEWED` deletion (§2.9 ranks 13<16<19 plus §3.5 already make the branch unreachable — impl still carries the check at `routes_requests.py:266`); `test_helpers` `create_batch` duplicate kwarg, `test_25`/`test_57` duplicate kwargs (fixture bugs); `test_46`/`test_58` back-dated `effective_from` (§3.3 pins it); `test_57` contract starting `ACTIVE` (§2.5/§3.6 pin `EXPIRED` as a clock-movement cascade; `routes_contracts.py:89` + `routes_clock.py:19-24`); `test_59` `NO_ACTIVE_PAYER_COLUMNS` (§3.10 pins); the `stale_analyses_for_item` wiring into `charge_item_lifecycle` (§3.6's "whenever the target item is mutated" already pins it — `routes_items.py:426`). I also left both known PRD-internal contradictions (approve OCC-vs-RESTRICTED, ingest capacity-vs-capture-hold) verbatim, since no traced edit touches those sites.

Orchestrator re-verification: `PRD_FINALIZED.md` = 545 lines / 118589 bytes vs `PRD.md` 545 lines / 117071 bytes; `diff` reports exactly 4 changed line pairs (8 diff lines), 29 headings preserved, file ends cleanly — non-truncated.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-01T01:52:00.000Z

Coverage pass complete. Final sweep this session read the remaining unread modules (`routes_pricing.py`, `validate.py`, `auth.py`, `envelope.py`, `store.py`, `derive.py`, `calc.py` in full, `routes_facilities.py` 1–115, `routes_capture.py` 1–40/96–176, `routes_code_update.py` 330–426) and produced three further pins; everything else was already aligned.

## Exit summary

**Files**: `PRD_FINALIZED.md` 545 lines / 118,589 bytes (118,132 chars) → `PRD_COMPLETED.md` 546 lines / 142,025 bytes (141,436 chars). **Char delta +23,304** (+23,436 bytes). The single added line is one extra bullet inside the existing §2.2 bullet list; no new sections, no new paragraphs. 60 paragraphs changed across 56 edit operations.

**Counts**: 69 distinct changes — **46 ambiguity-pins**, **23 mismatch-revisions**.

**§2 — platform**
- §2.1 — insert — ambiguity — DM scope test is skipped when the path id or body `department_id` does not resolve, deferring to the existence ranks — auth.py:55-71
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + 32 lowercase hex — envelope.py:14
- §2.2 — insert — ambiguity — `api_request_timestamp` is the system's only wall-clock read — envelope.py:12
- §2.2 — insert — ambiguity — unknown path or unaccepted method → `ERR_VALIDATION` (422) in the same envelope — app.py:35-41
- §2.3 — insert — ambiguity — mint sequence is the final tiebreak under a shared `created_at`, everywhere "ties broken by `created_at`" appears — store.py:118-121
- §2.5 — revise — mismatch — expiry sweep is `term_end_date` **strictly** earlier than now, one-way (never un-expires, never touches `TERMINATED`), each contract +1 version, endpoint returns 200 with empty `data` — routes_clock.py:14-25
- §2.7 — revise — mismatch — `Facility.version` bumps on **every** re-derivation, not only when a derived value changed — derive.py:54-60
- §2.7 — revise — mismatch — FROZEN gates **five** write operations; price-rule creation is deliberately ungated — routes_pricing.py:43-66
- §2.7 — revise — mismatch — re-derivation triggers replaced by the enumerated set actually implemented — derive.py:54
- §2.9 r10 — insert — ambiguity — `supersede_rule_id` and `change_request_id` join rank 10; absent/non-string body keys fall to rank 11 — routes_pricing.py:50-56
- §2.9 r11 — insert — ambiguity — absent/unparseable body ≡ `{}`, non-object body → `ERR_VALIDATION`, explicit null ≡ omission; ISO parsing is lenient (`T`/`t`/space, `Z`/`z`, optional seconds, numeric offsets normalised to UTC) — validate.py:11-20, store.py:14-42
- §2.9 r12 — insert — ambiguity — a present-but-non-integer `limit`/`offset` also lands at rank 12 — envelope.py:57-70
- §2.11 — insert — ambiguity — `capture_hold` is recomputed, not latched — derive.py:116
- §2.11 — revise — mismatch — cascade triggers are an enumerated set; `SUBMIT_FOR_REVIEW`/`RETURN_TO_DRAFT`/`APPROVE`/`ARCHIVE` bump only the item — routes_items.py:428-431

**§3.1–3.2**
- §3.1 — revise — mismatch — **five** governance knobs, not six — routes_facilities.py:45-51
- §3.1 — insert — ambiguity — PATCH semantics: all knobs optional, null/omitted keeps stored value, `name`/CCN not adjustable, OCC after schema — routes_facilities.py:88-111
- §3.1 — insert — ambiguity — revenue code creatable as `RETIRED`; retire is idempotent, cascades to nothing, bumps no version; list filters `code`/`status`/`pricing_class` — routes_facilities.py:127,147-149,176-186
- §3.1 — insert — ambiguity — omitted `allowed_revenue_code_values` → `[]`; `manager_user_id` uniqueness unenforced — routes_facilities.py:199-200
- §3.1 — revise — mismatch — `pricing_class` takes no part in price-rule selection; scope key is `(facility_id, revenue_code_id)` alone — routes_pricing.py:71-73
- §3.2 — insert — ambiguity — empty `markup_tiers` accepted, stored verbatim; ladder is a computation-time fallback, not a stored default — validate.py:167-192, calc.py:79-84
- §3.2 — insert — ambiguity — `flat_fee_cents` optional even under `FLAT_FEE`; null yields base 0 — calc.py:107
- §3.2 — insert — ambiguity — price rules may be wholly back-dated; `ERR_EFFECTIVE_DATE_IN_PAST` is item-creation-only — routes_pricing.py:65-66
- §3.2 — insert — ambiguity — unresolved `supersede_rule_id` → 404 regardless of would-be status — routes_pricing.py:50-56
- §3.2 — insert — ambiguity — `PSYCHOLOGICAL_99` applied arithmetically: 0 → −1 — calc.py:93
- §3.2 — revise — mismatch — markup compliance *computed* at four moments but *enforced* only at CR approve and item `APPROVE` — routes_requests.py:286, routes_items.py:364
- §3.2 — insert — ambiguity — approval reads the **stored** `projected_gross_charge_cents` (0 if null) and never rewrites the projections — routes_requests.py:280-285

**§3.3–3.5**
- §3.3 — insert — ambiguity — item creation never verifies the department belongs to the facility — routes_items.py:150-177
- §3.3 — revise — mismatch — lifecycle state check (13) precedes the FROZEN posture check (14) — routes_items.py:342-350
- §3.3 — revise — mismatch — REACTIVATE order: `REVENUE_CODE_RETIRED` → `PRICE_NOT_CURRENT` → `RETIRED_AS_DUPLICATE` — routes_items.py:400-409
- §3.3 — revise — mismatch — ARCHIVE order `IN_OPEN_BATCH` → `HAS_OPEN_REQUEST`; entry cascade narrowed to `MAPPED` entries in `MAPPING`/`CROSSWALK_APPROVED`/`CANCELLED`, target cleared, entry +1, cycle counters without bump — routes_items.py:410-417,435-459
- §3.4 — revise — mismatch — reprice admissible from every `price_status` except `PRICE_FROZEN`; order lifecycle → posture → frozen — routes_items.py:286-313
- §3.4 — insert — ambiguity — thaw is unconditional, with no sibling-file check — routes_transparency.py:172-179
- §3.5 — insert — ambiguity — proposal fields stored verbatim; `proposed_revenue_code_id` always FK-resolved at creation and resubmit — routes_requests.py:79
- §3.5 — insert — ambiguity — projection fallbacks for cost/revenue code; creation recomputes the department with a version bump — routes_requests.py:37-50,110
- §3.5 — revise — mismatch — REVIEW checks ARCHIVED (13) before SoD (18); a null `decision_note` preserves the stored one — routes_requests.py:182-209
- §3.5 — revise — mismatch — **approve fully reordered** to 13 → 15 → 16 → 18 → 19 → 23 → 54 (RESTRICTED before OCC, per §2.9) — routes_requests.py:240-290
- §3.5 — insert — ambiguity — implement's four preconditions incl. the undocumented DEACTIVATION-must-be-ACTIVE rule; `implementation_note` validated then discarded — routes_requests.py:364,384-399
- §3.5 — insert — ambiguity — implement writes cost only when non-null and rewrites `applied_price_rule_id`/`price_conflict` — routes_requests.py:401-411
- §3.5 — revise — mismatch — department recomputed only when a decision crosses the open/closed boundary — routes_requests.py:68-70,223

**§3.6–3.8**
- §3.6 — insert — ambiguity — off-method money fields silently nulled, but `percent_of_charge_bp` is retained — routes_contracts.py:84-86
- §3.6 — revise — mismatch — notice buffer consults the single nearest prior term, looks backwards only, compares exact elapsed duration to N×24h — routes_contracts.py:68-77
- §3.6 — insert — ambiguity — terminate discards its note and has no state precondition — routes_contracts.py:135-149
- §3.6 — insert — ambiguity — analysis creation resolves `change_request_id` as a body FK, has no request-state precondition, null projection → 0 — routes_contracts.py:160-174
- §3.6 — insert — ambiguity — `HISTORICAL_REPLAY` contract match ignores `product_line`; earliest-created same-payer term wins — calc.py:272-284
- §3.6 — insert — ambiguity — `COMPUTED → STALE` fires from exactly four places; code-cycle `ACTIVATE`/`ROLL_BACK` excluded — derive.py:193-225
- §3.7 — insert — ambiguity — entry payload never cross-checked against `action`; `new_revenue_code_id` not FK-resolved at creation — routes_code_update.py:116-141
- §3.7 — insert — ambiguity — MAP payload override, fixed check order, `ADD` maps with null target/carry, null `old_code_value` → `CROSSWALK_TARGET_NOT_FOUND` — routes_code_update.py:340,366-424
- §3.7 — revise — mismatch — APPROVE_CROSSWALK reordered SoD → `UNMAPPED_CODE_ENTRIES` → `CYCLE_HAS_NO_MAPPED_ENTRIES` — routes_code_update.py:211-221
- §3.7 — insert — ambiguity — ACTIVATE silently skips entries whose target is missing or `ARCHIVED`, and still succeeds — routes_code_update.py:296-298
- §3.7 — insert — ambiguity — cycle `version` advances exactly once per lifecycle action — routes_code_update.py:255-288
- §3.7 — insert — ambiguity — `APPLIED → REVERTED` is unconditional on rollback — routes_code_update.py:317-331
- §3.7 — revise — mismatch — the conservation invariant is a consequence of the cascade, not an enforced check — routes_code_update.py:296-331
- §3.7 — insert — ambiguity — CANCEL also clears `target_charge_item_id` — routes_code_update.py:281
- §3.8 — revise — mismatch — MARK_DUPLICATE order `TARGET_INVALID` → `IN_OPEN_BATCH` → `SIMILARITY_TOO_LOW` — routes_items.py:382-399
- §3.8 — insert — ambiguity — candidate report returns plain `ChargeItem` rows with no score field; decimal `min_score`, inclusive, applied before pagination — routes_items.py:264-280

**§3.9–3.10**
- §3.9 — revise — mismatch — **capacity (37) before capture-hold**, earliest breaching day reported, days enumerated by UTC-midnight truncation — routes_capture.py:39-46,61-78
- §3.9 — insert — ambiguity — reconcile advances `ChargeCaptureBatch.version` by exactly 1; the roll-up rewrites counters without a second bump — routes_capture.py:185-210
- §3.9 — revise — mismatch — CLOSE recomputes the department's **full** counter set including `open_request_count`, without bumping `Department.version` — routes_capture.py:260-261
- §3.9 — insert — ambiguity — CONFIRM's note optional; DISMISS bumps batch version and touches no department — routes_capture.py:400-401
- §3.9 — insert — ambiguity — RESOLVE does not recompute batch counters; recovery-line 404/422/`RECOVERY_LINE_INVALID` layering — routes_capture.py:343-378
- §3.9 — insert — ambiguity — `expected_charge_cents`/`line_variance_bp` null on every line that never reaches test 4, and reset to null at the start of each pass — calc.py:384-385
- §3.9 — insert — ambiguity — a null `expected_charge_cents` contributes 0 to `total_expected_charge_cents` — calc.py:421-425
- §3.10 — insert — ambiguity — build has no posture gate; OCC runs after schema — routes_transparency.py:40-47
- §3.10 — insert — ambiguity — `content_hash` is hex SHA-256 over `cdm_number|code|code_value|gross` with the four-digit revenue `code`; worked example; empty set hashes the empty string — calc.py:538-550
- §3.10 — insert — ambiguity — `validation_errors` fixed order, each string at most once — calc.py:551-563
- §3.10 — revise — mismatch — VALIDATE re-runs the **entire** build against the stored `as_of_datetime` — routes_transparency.py:135-141
- §3.10 — insert — ambiguity — PUBLISH does not rebuild; it republishes validation's figures — routes_transparency.py:132-133
- §3.10 — revise — mismatch — supersession-from-outside now points at §2.11's enumerated trigger set instead of "a lifecycle change" — derive.py:81-85

**Both named PRD-internal contradictions resolved toward §2.9** (§3.5 approve: RESTRICTED 15 before OCC 16; §3.9 ingestion: capacity 37 before capture-hold), plus four further §3-vs-§2.9 ordering contradictions of the same family that were not named (§3.3 ARCHIVE, §3.3 REACTIVATE, §3.7 APPROVE_CROSSWALK, §3.8 MARK_DUPLICATE).

**Verified, no edit needed**: §2.6, §2.8, §2.10; the §4 endpoint table (58/58 rows, exact method+path and role columns) and the §5 error catalogue (65/65 codes with identical HTTP statuses) were checked programmatically against `implementation/` with zero diffs.

Orchestrator re-verification: `PRD_COMPLETED.md` = 546 lines / 142025 bytes; 29 headings (identical count to `PRD.md` and `PRD_FINALIZED.md` — no section added or lost); 65 distinct `ERR_*` codes still present; 125 diff lines vs `PRD_FINALIZED.md`; file ends cleanly — non-truncated. Confirmed Steps 8 and 9 modified no file under `implementation/`, `test_suite/`, or `test_helpers/` (only the pre-existing `results.{1..8}.json` from the Step 7 sweep carry later mtimes).

## Pipeline complete — 2026-09-01T01:55:00.000Z

All 9 steps done. Final artifact inventory in `task_2193_chargemaster_maintenance_pricing_governance/`:

| Artifact | Size |
| --- | --- |
| `SCAFFOLD.yaml` | 2165 lines / 169042 B — 14 entities, 10 state machines (48 transitions), 9 calculations, 66 validations (ranks 1–54), 58 endpoints, 65 errors, 6 roles, 2 OCC rules |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 4872 lines — 22 instances across all 9 §0.5 rule families (≥2 each) |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 9140 lines — 96 instances (93 real + 3 `excluded_because` stubs) across 9 sections |
| `workspace/INSTRUCTION.md` | copied from project root |
| `workspace/PRD.md` | 545 lines / 117071 B |
| `test_helpers/` | 10 modules / 2590 lines |
| `test_suite/` | 77 modules + conftest / 11140 lines / **137 test functions**, every docstring design-tagged |
| `workspace/implementation/` | 17 modules / 4104 lines + `start.sh` + `requirements.txt`, in-memory only, zero seeded data |
| `workspace/PRD_FINALIZED.md` | 545 lines / 118589 B — 4 lines revised over PRD.md |
| `workspace/PRD_COMPLETED.md` | 546 lines / 142025 B — 69 changes (46 ambiguity-pins, 23 mismatch-revisions) |

Final test state: **137/137 passing in all 8 rounds** of a parallel `--isolation per-test-server` stability sweep; 0 skip/xfail markers.

Intermediate artifacts retained rather than deleted: `SCAFFOLD_DIFFICULTY_PART_{A,B,C}.yaml` (the three per-rule-family fragments merged into `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — kept as provenance for the stall workaround) and `workspace/implementation/results.{1..8}.json` (Step 7's final sweep output).

## Resume #6 — 2026-08-31T19:52:00.000Z

Previous run crashed a sixth time during Step 2. Re-verified on-disk state via `find`: only `worklog.md` and `workspace/INSTRUCTION.md` exist; `diff` against project-root `INSTRUCTION.md` is clean (53 lines). No `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `workspace/PRD.md`, `test_helpers/`, `test_suite/`, `workspace/implementation/`, `PRD_FINALIZED.md`, or `PRD_COMPLETED.md`. Steps 1 and 3 confirmed valid and NOT redone; pipeline resumed from Step 2 in the same task directory.
