# Worklog — task_2576_condominium_conversion_public_offering_statement

## Step 1: Create task directory — 2026-09-03T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2576_condominium_conversion_public_offering_statement` and its `workspace/` subdirectory. Index 2576 was pre-assigned by the orchestrating prompt; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2a: Generate SCAFFOLD.yaml (§1.0–§1.7) — 2026-09-03T00:00:00.000Z

ORCHESTRATOR NOTE (decision recorded per AUTONOMY): the first Step 2 subagent — asked to produce all three scaffold files in one run — was terminated by the platform with `max_output_tokens` (64000-token single-response cap) and left ZERO files on disk. This matches the known `prd-bench-generator-64k-output-cap` failure mode. Rather than retry the same monolithic shape, I partitioned Step 2 into three sequential subagents (2a = SCAFFOLD.yaml §1.0–§1.7, 2b = SCAFFOLD_DIFFICULTY_DESIGN.yaml §1.8, 2c = SCAFFOLD_CORNER_DESIGN.yaml §1.9), each under a hard protocol of one `cat >>` append of <180 YAML lines per assistant turn. 2b and 2c are run sequentially rather than concurrently because both are permitted to widen §1.5 via the priority ladder and would otherwise write-conflict on SCAFFOLD.yaml; 2c additionally needs 2b's instance `name:` values for its `excluded_because:` stubs.

Subagent summary (verbatim):

Part 1 of 3 is complete and verified.

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_2576_condominium_conversion_public_offering_statement/SCAFFOLD.yaml` — 4720 lines, parses under `yaml.safe_load`.

**Top-level keys:** `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles`. `scaffold_difficulty_design` and `scaffold_corner_design` are **absent** (confirmed programmatically).

**Counts:** entities 14 · state_machines 12 entries (8 entities; parallel dimensions expressed via an extra `state_field:` key) · concurrency_rules 4 · calculations 12 · validations 50 · endpoints 97 · errors 50 · roles 9.

**complexity_profile:** `primary_archetype: compliance_audit`, `secondary_archetype: workflow_orchestration`, layers `[dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency]`, `entity_topology: graph`, `state_machine_shape: parallel`, relationships `[one_to_many, many_to_many, cross_aggregate]`, `role_model: segregation_of_duties`, `consistency_model: immediate`.

**Entities:** ConversionProject, EngineeringReport, MajorComponent, SuitabilityAssessment, DeclarationPackage, Unit, PublicOfferingStatement, POSSection, TenantHousehold, ReserveStudy, InitialBudget, ClosingBatch, PurchaseAgreement, WarrantyClaim.

**State machines (entity / state_field / shape):** ConversionProject/`status` (7 states, 3 reverse edges) + ConversionProject/`posture` (OPEN·RESTRICTED·FROZEN, compound-derived) · EngineeringReport/`status` (cycle DRAFT→SUBMITTED→REVISION_REQUESTED→DRAFT, ACCEPT/REJECT branch, terminal SUPERSEDED) · DeclarationPackage/`status` (with PLAT_CERTIFIED→DRAFT revert) · PublicOfferingStatement/`status` (cycle EFFECTIVE→AMENDMENT_FILED→EFFECTIVE) · TenantHousehold/`notice_status`,`rofr_status`,`relocation_status` (3 parallel dims) · PurchaseAgreement/`contract_status` (HARD→SIGNED cycle) + `escrow_status` · ClosingBatch/`status` (THRESHOLD_MET↔THRESHOLD_SHORT, RELEASED→THRESHOLD_SHORT) · WarrantyClaim/`status` (ADMIT/DENY branch + REMEDIATED→REOPENED cycle bounded at MAX_CLAIM_REOPENS=2).

**Calculations:** building_suitability_score, reserve_funding_requirement, initial_budget_developer_deficit, unit_assessment_allocation, percentage_interest_reallocation, tenant_notice_and_relocation, rescission_deadline, warrantability_ratios, presale_threshold_evaluation, project_posture_derivation, warranty_charge_and_window, escrow_and_obligation_conservation.

**Roles / identity:** ConverterSponsor, LicensedEngineer, PeerReviewEngineer, StateRegulator, EscrowAgent, LenderUnderwriter, PlatformAdmin (all `opaque`); TenantOccupant (`entity_backed:TenantHousehold`); Purchaser (`entity_backed:PurchaseAgreement`).

**Nine Difficulty Rules — two qualifying instances each (index for §1.8):**
1. `dual_variant_calc` — `building_suitability_score` (AS_INSPECTED vs POST_REMEDIATION, divergent via `planned_remediation_gain_years`); `warrantability_ratios` (CONTRACT_BASIS vs CLOSED_BASIS, two separately persisted verdicts). Also available: reserve_funding_requirement, rescission_deadline, warranty_charge_and_window.
2. `combinatorial_formula` — `initial_budget_developer_deficit` (7 pinned steps: base → single-pass tier @800/650/500 bp with no re-tiering → fee → total → assessment income → deficit → subsidy flag); `tenant_notice_and_relocation` (notice tier 120/180/270 + 45/90 protected extension, then relocation multiplier→cap→uplift→cap→floor in pinned order).
3. `non_linear_state_machine` — `WarrantyClaim.status` (ADMIT/DENY branch with disjoint side effects + bounded REMEDIATED→REOPENED→TRIAGED_ADMISSIBLE cycle); `TenantHousehold` (three parallel dimensions moved together by one notice, then decoupled by ROFR EXERCISE).
4. `transitive_cascade` — material amendment, 4 hops: POS `AMENDMENT_FILED` → PurchaseAgreement `HARD→SIGNED` + deadline restart → ClosingBatch `→THRESHOLD_SHORT` → ConversionProject `CLOSINGS→PRESALE`; unit withdrawal, 5 hops: Unit `→WITHDRAWN` → agreements `→VOID` → escrow `FUNDED→REFUNDED` + project ledger → batch `→THRESHOLD_SHORT` → DeclarationPackage `PLAT_CERTIFIED→DRAFT` + bp re-sweep.
5. `priority_pair_validation_conflict` — p24 `ERR_BATCH_NOT_RELEASED` (state) wins over p48 `ERR_ESCROW_NOT_FUNDED` (business_fiscal) on `POST /purchase-agreements/{id}/closing`; p34 `ERR_ROFR_WINDOW_EXPIRED` (business_temporal) wins over p41 `ERR_ROFR_UNIT_NOT_LINKED` (business_referential) on rofr-responses. Two more exist: p29 vs p43 on plat-certification, p35 vs p48 on hardening.
6. `boundary_precision_check` — `presale_threshold_evaluation` inclusive `>=` (26/51 = 50.98 fails a 51.00 threshold, 27/51 = 52.94 passes); `rescission_deadline` asymmetric comparators (rescind strict `clock <`, harden inclusive `clock >=`, so the exact deadline instant belongs to hardening only). Also: `unit_assessment_allocation` round-per-unit-then-sum with residual to the highest `percentage_interest_bp` and `created_at ASC` tie-break; `CRITICAL_RUL_YEARS` strict `<` (exactly 5 years passes).
7. `cross_entity_state_dependency` — `POST /closing-batches/{id}/release` requires project posture OPEN + DeclarationPackage RECORDED + threshold met + *every* assigned agreement HARD/CLOSED; `POST /public-offering-statements/{id}/effectiveness` requires all nine POSSections COMPLETE + DeclarationPackage RECORDED + InitialBudget ADOPTED whose ReserveStudy is ADOPTED.
8. `resource_temporal_overlap` — ClosingBatch windows: **half-open** `[start, end)`, adjacency allowed, no buffer, at most one occupant per instant (p38 `ERR_BATCH_WINDOW_OVERLAP`); WarrantyClaim remediation windows: **closed** `[start, end]` + 259200 s cooldown on the same MajorComponent (p39) *plus* a project-wide aggregate depth cap `max_overlapping_remediations` (p40) — deliberately different geometry, buffer and aggregation.
9. `compensating_invariant` — escrow cash conservation `deposits_received == balance + refunded + disbursed` (delta field must always read 0) and the 10000-basis-point undivided-share invariant where `withdraw` then `reinstate` restores byte-identical `percentage_interest_bp`; relocation obligation reversal on ROFR EXERCISE (`ACCRUED→CANCELLED` or `PAID→REVERSED`) with its own always-zero reconciliation delta.

**Notes for the parent / sibling agents**
- `POST /_clock/set_current_utc` is declared with the mandatory startup default `2026-08-01T00:00:00Z` stated in its `description:`; `GET /_clock/current` is also declared.
- All 27 canonical FKs pass reverse-reachability; I ran `scaffold_lint.py` with stub §1.8/§1.9 files and it reports **clean lint** (97 endpoints, 14 entities, 0 violations).
- Two corrections made during verification that downstream agents should know about: (a) `api_prefix` is `""` (this scaffold uses top-level collections `/conversion-projects`, `/engineering-reports`, `/units`, …) — a non-empty prefix broke lint check (f)'s collection-segment inference; (b) optional inputs are written **quoted** (`"status?"`) because PyYAML cannot parse a bare `?`-suffixed token inside a flow sequence — the lint strips the `?` correctly.
- Deliberate overshoot vs the stated bands: 97 endpoints and 50 errors exceed the 26–34 / 22–30 Expert guidance. This is driven by hard constraint 6 (generous, testability-complete §1.5: every FK reverse GET, every summary computed-read, every adjustment endpoint) and the "harder than expert" target. Density is preserved — there are no orphan tables; every entity participates in at least one cascade, calculation and validation.
- Forbidden vocabulary count is 0; the only write-write conflict mechanism is OCC on parent `version` (4 rules, all 412, each with a required `expected_<parent>_version` input and a parent version bump).

## Step 2b: Generate SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8) — 2026-09-03T00:00:00.000Z

Subagent summary (verbatim):

Done. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` is complete, schema-conformant and lint-clean.

## Deliverable
`/home/ubuntu/github/CodingPRD/tasks/task_2576_condominium_conversion_public_offering_statement/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design:`, 9 rule blocks in the mandated order, 2 instances each = 18. `SCAFFOLD_CORNER_DESIGN.yaml` was created only as a `scaffold_corner_design: []` stub to satisfy the linter and has been **deleted**.

## Instances per rule
1. **dual_variant_calc** — `suitability_score_as_inspected_vs_post_remediation`, `warrantability_contract_basis_vs_closed_basis`
2. **combinatorial_formula** — `budget_single_pass_fee_tier_no_retier_on_total` (mode c), `tenant_notice_tier_branch_cap_uplift_cap_floor` (mode a)
3. **non_linear_state_machine** — `warranty_claim_triage_fork_and_bounded_reopen_cycle`, `tenant_household_three_parallel_state_dimensions`
4. **transitive_cascade** — `material_pos_amendment_cascade_pos_agreement_unit_project`, `unit_withdrawal_cascade_unit_agreement_escrow_batch_project`
5. **priority_pair_validation_conflict** — `pos_not_delivered_beats_escrow_not_funded_on_hardening`, `rofr_window_expired_beats_rofr_unit_not_linked`
6. **boundary_precision_check** — `presale_pct_inclusive_at_exact_threshold_equality`, `rescission_deadline_strict_vs_inclusive_at_same_instant`
7. **cross_entity_state_dependency** — `closing_blocked_until_assigned_batch_is_released`, `pos_effectiveness_blocked_until_declaration_recorded`
8. **resource_temporal_overlap** — `closing_batch_half_open_window_adjacency_allowed`, `remediation_closed_interval_cooldown_and_depth_cap`
9. **compensating_invariant** — `escrow_cash_conserved_across_fund_then_rescind`, `undivided_share_bp_restored_byte_identically_by_withdraw_then_reinstate`

## SCAFFOLD.yaml edits
**NONE.** Every instance was realizable from existing §1.5 endpoints (rung 1 of the priority ladder); the pre-existing `POST /_clock/set_current_utc` covered all temporal probes. `git status` confirms SCAFFOLD.yaml is untracked-but-unmodified since the scaffold author wrote it.

## Formula literals (all executed in python3, not hand-derived)
- Suitability: AS_INSPECTED **65.83** / POST_REMEDIATION **87.50**.
- Budget (2 units, opex 875000): base **1000000**, fee tier bp **800**, fee **80000**, total **1080000**; per-unit annual 540000, monthly 45000; after withdrawal survivor 1080000 / 90000. Single-pass check: re-tiering on the *total* would give bp 1000 — proven not to happen.
- bp sweep, bases 3333/3333/3334: **3333/3333/3334** (residual 0) -> withdraw the 3334 -> **5000/5000** -> reinstate -> **3333/3333/3334** byte-identical; total 10000 at every step.
- Presale: `round_half_up(100*1/2, 2)` = **50.00**; thresholds 49.99 -> True, **50.00 -> True (equality passes)**, 50.01 -> False.
- Rescission deadline **2026-08-16T00:00:00Z**: at `...15T23:59:59Z` rescission allowed / hardening refused (p35); at `...16T00:00:00Z` rescission refused (p36, strict `<`) / hardening allowed.
- Warranty: FOUNDATION cap `round_half_up(10000000*6000/10000)` = **6000000**, ROOF cap **2400000**; expiries **2031-07-06T00:00:00Z** (60 mo) / **2028-07-21T00:00:00Z** (24 mo).
- Remediation cooldown 259200 s off end 2026-09-03: colliding start **2026-09-06T00:00:00Z** (equality collides), first clean start **2026-09-06T00:00:01Z**; aggregate depth probes -> [09-02,09-02T12] depth 2 fail, [09-03,09-04] depth 2 fail (shared end instant counts in both, closed intervals), [09-11,09-12] depth 1 pass. Reserve charge total **5500000**.

## Verification results
- Structure: `order ok: True`, 9 blocks, 2 each, `total: 18 >=18: True`, names unique, no snake_case violations, every instance has `setup`/`setup_api_calls`/structured list `trigger`/list-of-strings `assert`.
- Placeholder closure (payloads, `as_user_id`, paths **and** assert prose, across setup_api_calls->trigger in order): **unbound placeholders: 0**.
- Grounds resolvability (parsed against SCAFFOLD.yaml): **bad grounds: 0**, no duplicate refs.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    97
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     0
  Calls scanned (§1.8+§1.9):  541

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Defects found and fixed during self-verification
- **Scaffold-author index deviation:** the claimed p24 (`ERR_BATCH_NOT_RELEASED`) vs p48 (`ERR_ESCROW_NOT_FUNDED`) conflict pair is **unrealizable** — a HARD agreement is always FUNDED, so the two guards can never be simultaneously violated. Substituted **p28 `ERR_POS_NOT_DELIVERED` vs p48** on `POST /purchase-agreements/{id}/hardening`, which is realizable and still crosses the state/fiscal category boundary §0.5 requires.
- Grounds `state_machines.Unit.INCLUDED_to_WITHDRAWN` / `..WITHDRAWN_to_INCLUDED` (3 instances) did not resolve — **Unit has no declared state machine**; replaced with `entities.Unit.fields.declaration_status`.
- Grounds `concurrency_rules[escrow-cash-conservation]` did not exist -> `state_machines.PurchaseAgreement.FUNDED_to_REFUNDED`.
- `POST /closing-batches/{id}/release` is **EscrowAgent-only**; two calls (and one assert line) used ConverterSponsor — corrected.
- Non-existent PurchaseAgreement fields `hardened_at` / `rescinded_at` asserted in 4 places -> re-expressed via the real `closed_at`.
- Wrong InitialBudget field names `total_annual_budget_cents` / `assessment_base_cents` -> `total_annual_expense_cents` / `base_expense_cents`.
- 9a's posture assertion said RESTRICTED; replaying `project_posture_derivation` clause-by-clause yields **OPEN** — fixed.
- 5a's repair-retry would have tripped p35 before p48; the retry now advances the clock to `2026-08-16T00:00:00Z` so ERR_ESCROW_NOT_FUNDED actually surfaces.
- ROFR expiry is **inclusive**, so p34 needs `2026-10-30T00:00:01Z`; the rewind control probe at `...00:00:00Z` returns ERR_ROFR_UNIT_NOT_LINKED, proving the ordering rather than asserting it.
- Schema repair: instances 4b-9b were initially drafted with prose `trigger: |` / `assert: |` block scalars; all were converted to §1.8's structured call list + one-observable-per-line assert list. Negative triggers use `captures: { err_id: $.data.error_id }` so `scaffold_lint.py`'s `is_negative_trigger()` correctly relaxes role/payload checks on the intentionally-failing call.

## Step 2c: Generate SCAFFOLD_CORNER_DESIGN.yaml (§1.9) — 2026-09-03T00:00:00.000Z

Subagent summary (verbatim):

PART 3 OF 3 complete. `SCAFFOLD_CORNER_DESIGN.yaml` is written and passes all four mandated verification checks.

## Deliverable
`SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design:`, 9 sections in guide order, ~6570 lines, **106 instances = 77 recipes + 29 `excluded_because:` stubs** (target was 60-85 recipes).

### Per-section counts (recipes / stubs)
entities 11 (8/3) · state_machines 17 (12/5) · calculations 14 (10/4) · validations 14 (10/4) · endpoints 8 (6/2) · errors 21 (18/3) · rbac 8 (5/3) · cross_cutting_complexity_layers 9 (6/3) · consistency_model 4 (4/0)

RBAC denials cover 8 of 9 roles. Response envelope, pagination defaults (limit 10 / min 1 / max 100 / offset 0 — including `limit: 0`, `limit: 101`, `offset: -1`, and the accepted `limit: 100, offset: 0` boundary), required-field-missing, left-to-right 404 ordering, FK referential integrity, and computed-field correctness are each covered; all 4 `concurrency_rules[]` stale-version rejections have dedicated recipes.

(Full 106 instance-name list omitted here for length; it is in SCAFFOLD_CORNER_DESIGN.yaml itself. Section counts and the checks below are the durable record.)

### Error-id coverage
`check3 error ids missing: []` — all **50** `errors[]` ids are reached: 33 asserted with an exact `error_id` + HTTP status in a negative recipe, the remainder cited by a warranted stub. An extra cross-check confirmed every asserted `ERR_*` also asserts its declared status (`mismatches 0`).

### SCAFFOLD.yaml edits (6, all surgical Edits — no rewrite; ladder rung 2/3 never needed, no new endpoint added)
1. `POST /conversion-projects` side_effects: `posture := OPEN`, `suitability_gate := NOT_EVALUATED` -> `RESTRICTED` / `UNEVALUATED` — the written values were not in the declared enums.
2. `PATCH /major-components/{id}` side_effects: `NOT_EVALUATED` -> `UNEVALUATED` — same undeclared enum value.
3. `POST /conversion-projects/{id}/posture-recalculations` side_effects: dropped `WarrantyClaim.status ... -> EXPIRED` (EXPIRED is not a declared WarrantyClaim status) and replaced it with the declared `REMEDIATED -> CLOSED for claims whose warranty_expires_at < clock`.
4. Global `READY_FOR_REVIEW` -> `SECTIONS_COMPLETE` (5 occurrences) — `READY_FOR_REVIEW` is not a declared POS status.
5. `PUT /public-offering-statements/{id}/sections/{section_code}` description: removed the `MISSING` content_status branch — not a declared value.
6. `POST /conversion-projects/{id}/public-offering-statements`: description + side_effects `content_status MISSING` -> `DRAFTED` — `POSSection.content_status IN {DRAFTED, COMPLETE}`.

### Python snippets run for pre-computed asserts (final consolidated run)
```
1 ROOF 10000000/RUL30/EXCELLENT              -> 100.00  cap=False PASSED
ROOF 9000000/30/EXC + ELEV 1000000/RUL4/GOOD -> 40.00   cap=True  FAILED
ROOF 9000000/30/EXC + ELEV 1000000/RUL5/GOOD -> 91.17   cap=False PASSED
FOUNDATION 4000000/RUL1/POOR                 -> 0.00    cap=False FAILED
ffb 2500000   rac COMPONENT 333334
base 1333334  bp 800  fee 106667  total 1440001
two units annual [720000, 720001] monthly [60000, 60000] income 1440001
one unit  annual 1440001 monthly 120000
opening 1750000 -> pf_bp 7000 -> ADEQUATE
opening 1749875 -> pf_bp 7000 -> ADEQUATE   (exact 6999.50, half-up)
opening 1749874 -> pf_bp 6999 -> UNDERFUNDED
verified aggregate 10000000 + 4000000 = 14000000
```
Earlier snippets carried into asserts: warranty windows 62208000 s -> `2028-07-21T00:00:00Z` (non-structural) and 155520000 s -> `2031-07-06T00:00:00Z` (structural); RUL5 life-safety mix 92.42; rescission deadlines 2026-08-16 / 2026-08-08 / 2026-08-06; tenant 7-month notice -> vacate 2026-11-29, ROFR 2026-10-30, relocation 900000; bp reallocation after withdrawing 3333 -> [4999, 5001].

### Scaffold defects found (for the PRD author)
1. **`ERR_NO_INCLUDED_UNITS` (priority 45) is unreachable** — every path that could present an empty INCLUDED set is blocked by an earlier-priority check. It is the only error id with no assert of its own.
2. `ERR_PERCENTAGE_INTEREST_NOT_BALANCED` (p43) is reachable **only** via plat-certification on a package with an empty INCLUDED set.
3. §1.2's `SUBMITTED->ACCEPTED` precondition `verified_component_count >= 1` combined with "verification is the only writer of VERIFIED" means every accepted-report path needs an explicit `POST /major-components/{id}/verification`; §1.5's submit prose does not say so.
4. `POST /conversion-projects/{id}/reserve-studies` description requires an ACCEPTED report, but no declared validation/error enforces it (only p30/p31 apply).
5. `ClosingBatch.qualifying_agreement_count` field description says `contract_status IN {HARD, CLOSED}` while `calculations.presale_threshold_evaluation` says `{SIGNED, HARD, CLOSED}` — asserts were chosen to hold under both readings.
6. §1.2's TenantHousehold relocation transition lists actor ConverterSponsor while §1.5/§1.7 make `POST /tenant-households/{id}/relocation-disbursements` EscrowAgent-only.
7. Implementer trap worth an explicit PRD sentence: `Unit.percentage_interest_bp` and `DeclarationPackage.allocated_bp_total` remain 0 until plat-certification, so any per-unit assessment split must certify before the budget create.

### Lint verdict (verbatim)
```
Coverage
  §1.5 endpoints declared:    97
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     77
  Calls scanned (§1.8+§1.9):  1390

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Other checks: `check2 issues: []` (no instance has both `test_recipe` and `excluded_because`; every `difficulty_instance` resolves to one of the 18 §1.8 names; names unique across the union of both design files with `overlap with 1.8: set()`; zero unbound `${var}`), assert-field-name checker `bad: 0`, enum/field-domain checker `0`.

### ORCHESTRATOR ADDENDUM to Step 2c

The subagent's prose summary mis-named three RBAC roles (`TenantRightsCoordinator`, `PurchaserRepresentative`, `ClosingCoordinator`). I cross-checked the YAML directly: every `as:` value across BOTH design files (1390 calls) resolves to one of the nine real §1.7 roles — ConverterSponsor, LicensedEngineer, PeerReviewEngineer, StateRegulator, EscrowAgent, LenderUnderwriter, PlatformAdmin, TenantOccupant, Purchaser — with `roles NOT in scaffold: []`. The slip is confined to the prose summary; the artifact is correct.

I then fixed the two genuine SCAFFOLD.yaml self-inconsistencies the subagent reported as defects 5 and 6, because leaving them would make the doc generator write mutually contradictory PRD prose and would guarantee avoidable Step 7 churn:
- Defect 5: `entities.ClosingBatch.fields.qualifying_agreement_count.description` now reads `contract_status IN {SIGNED, HARD, CLOSED}`, matching `calculations.presale_threshold_evaluation`'s formula (the formula is authoritative — it is the executable definition, and both design files were written against it).
- Defect 6: `state_machines.TenantHousehold.relocation_status` transition `ACCRUED -> PAID` now carries `actor: EscrowAgent`, matching both §1.5 (`roles: [EscrowAgent]`) and §1.7 (EscrowAgent `exclusive_operations`). Two of three sources already agreed; the lone `actor:` field was the outlier.
Defects 1-4 and 7 are informational (unreachable-by-construction error ids, an under-enforced description clause, and an implementer trap) and are left for the doc generator and Step 9 to resolve in prose rather than patched into the scaffold.

Re-verified after both edits: `yaml.safe_load` parses, and `scaffold_lint.py` still reports `VERDICT: clean lint` (97 endpoints, 14 entities, 18 + 77 instances, 1390 calls).

## Step 3: Copy shared files — 2026-09-03T00:00:00.000Z

`cp /home/ubuntu/github/CodingPRD/INSTRUCTION.md workspace/INSTRUCTION.md` (53 lines).

## Step 4: Generate PRD.md — 2026-09-03T00:00:00.000Z

ORCHESTRATOR NOTE (decision recorded per AUTONOMY): a single doc-generator subagent could not produce this PRD — the scaffold surface is 14 entities / 12 state machines / 66 transitions / 12 calculations / 50 validations / 97 endpoints / 50 errors, and one agent writing all of §1-§5 would have hit the same 64000-token response cap that killed the monolithic Step 2 attempt (and would risk exactly the silent trailing-section truncation this pipeline is known for). I therefore partitioned Step 4 into three CONCURRENT part-writers, each producing a separate part-file that I concatenated myself, and I ran the doc-generator's three Hard Contracts as mechanical checks in the orchestrator rather than trusting a self-report:
  - 4a -> workspace/_prd_part_1_2.md  (title + §1 Introduction + §2 Global Specifications)
  - 4b -> workspace/_prd_part_3.md    (§3 Business Logic & Workflows — the scattering zone)
  - 4c -> workspace/_prd_part_4_5.md  (§4 Endpoint table + §5 Error catalogue)
All three were forbidden from reading SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml, per the skill's withholding rule. Concurrency was safe because the three write disjoint files; §2/§3 zone overlap was handled by giving 4a the "precise zone" invariants and 4b the per-workflow detail. Part-files were deleted after assembly.

Assembled: workspace/PRD.md, 901 lines, headings §1, §2 (2.1-2.9), §3 (3.1-3.9), §4, §5 — ascending, no gaps.

### Orchestrator-run Hard Contract verification on the ASSEMBLED PRD.md (not self-reported)
- **Contract 1 — field-name coverage: PASS.** All ~220 `entities[].fields[].name` present backticked (0 missing); all endpoint `input:` identifiers across all 97 endpoints present (0 missing); all path parameters present (0 missing).
- **Contract 2 — rule coverage: PASS on every mechanical proxy.** All 50 `errors[].id` present (0 missing); every state value across all 12 state-machine blocks present (0 missing); **all 66 transitions present as explicit `FROM -> TO` backticked pairs (0 missing)**.
- **Contract 3 — §3 path purity: PASS.** Zero HTTP-method leaks in §3 (the only `POST` substring anywhere in §3 is the enum literal `POST_REMEDIATION`, which Contract 1 requires verbatim); zero slash-bearing lines in §3 at all.
- Forbidden concurrency vocabulary across the whole PRD: 0 matches for simultaneous / at the same time / concurrently / in parallel / first-writer / race winner / race loser.
- §4 table: header exactly `Method | Path | Description | Authorized Role(s)`, 97 data rows, `(method, path)` sequence exactly equal to `endpoints[]` in scaffold order, 0 malformed cell counts.
- §5 table: header exactly `Error ID | HTTP Status Code`, 50 data rows, `(id, http)` sequence exactly equal to `errors[]` in scaffold order, 0 malformed cell counts.
- **Truncation guard (the known doc-generator failure):** `tail` of PRD.md ends on the final §5 table row `| ERR_PRESALE_THRESHOLD_NOT_MET | 409 |` — a real section boundary, not mid-sentence. No regeneration needed.
- Leak check: 0 occurrences of "harder than expert", "scaffold_difficulty", "scaffold_corner", "test_recipe", or "hard contract" in PRD.md.

### 4a summary (verbatim)
482 lines. §2.x subsections: 2.1 Acting Identity and Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination of Registry Collections · 2.4 The Logical Registry Clock · 2.5 Registry Record Identity, Revision Counters and Cascade Propagation · 2.6 Path Resolution and the Order of Rejection · 2.7 Optimistic Concurrency on Shared Parent Records · 2.8 Cents, Basis Points, Percentages and Day-Multiples: Precision Discipline · 2.9 Conserved Quantities: Escrow Cash, Undivided Interest and Relocation Obligation.
All nine roles individually named with their `identity:` translated (seven `opaque` — ConverterSponsor->`sponsor_user_id`, LicensedEngineer->`submitted_by_user_id`, PeerReviewEngineer->`reviewed_by_user_id`, StateRegulator->`attested_by_user_id`, EscrowAgent/LenderUnderwriter/PlatformAdmin with no recorded field; TenantOccupant->`entity_backed:TenantHousehold`; Purchaser->`entity_backed:PurchaseAgreement`). All 14 entities have `common_fields: true`, so §2.5 states none omits `updated_at`/`version`.
§2.6 renders the validation priority order as an 8-rung ladder: auth (1) -> authorization/identity/SoD (2-4) -> existence left-to-right, eight 404 families then body-borne id families (5-12) -> `ERR_PROJECT_SCOPE_MISMATCH` (13) -> request shape/pagination/duplicate key (14-16) -> OCC (17-20) -> posture gates + state preconditions (21-28) -> business rules safety->temporal->referential->constraint->fiscal (29-50).
The four OCC rules as rendered, all REQUIRED, all 412, framed purely as stale-version rejections: `expected_unit_version`/`ERR_STALE_UNIT_VERSION` (agreement against a unit); `expected_engineering_report_version`/`ERR_STALE_REPORT_VERSION` (suitability assessment); `expected_conversion_project_version`/`ERR_STALE_PROJECT_VERSION` (initial budget); `expected_closing_batch_version`/`ERR_STALE_BATCH_VERSION` (agreement-to-batch assignment). §2.7 states these four are the only endpoints taking a version field.
§2.2 diff against `skills/prd-bench-doc-generator/section-2.2-response-structure.md`: **no differences — byte-for-byte identical**, `"data": { }` preserved.

### 4b summary (verbatim)
257 Markdown lines / 14,746 words / 107,681 bytes. §3.x subsections: 3.1 Project Intake, the Building Posture Gate, and the Logical Clock · 3.2 Engineering Reports, Component Inventories and Independent Peer Review · 3.3 Scoring Building Suitability and Setting the Suitability Gate · 3.4 The Declaration, Bylaws and Plat: Unit Boundaries and the Undivided-Interest Sweep · 3.5 Reserve Funding Studies and the First-Year Budget · 3.6 Existing Tenants: Statutory Notice, the Right of First Refusal and Relocation Assistance · 3.7 The Public Offering Statement: Statutory Sections, Effectiveness and Amendments · 3.8 Selling Units: Contracts, Escrow, the Rescission Window and Lender Warrantability · 3.9 Closing Batches, Release Sequencing, Project Completion and Common-Element Warranty Claims.
Self-checks: path purity clean (file contains no `/` character at all); 0 forbidden-concurrency matches; 0 missing field/input names; 0 of 50 errors missing; 0 missing enum members after backticking `management_fee_bp` members 500/650/800; all 66 transitions rendered as explicit `FROM -> TO` pairs (12 were prose-only on the first pass and were rewritten).

**Twelve scaffold inconsistencies 4b found and how the prose resolves them** (recorded here because Steps 8/9 will meet them again):
1. TenantHousehold endpoint prose uses `PENDING`/`NOT_ELIGIBLE`/`WITHDRAWN`/`CANCELLED` while entity constraints and state machines use `PRE_NOTICE`/`NOT_OWED`/`NOTICE_WITHDRAWN`/`REVERSED` — **entity constraints win**.
2. Warranty triage endpoint says `triage_outcome := ADMIT/DENY` and `status := TRIAGED_DENIED`; entity constraints say `PENDING/ADMISSIBLE/DENIED` and status `DENIED` — **entity constraints win**.
3. Project-create description says posture `OPEN`; default and side effects say `RESTRICTED` — **`RESTRICTED`**.
4. `revision_round` increments on submission only (state machine), not on rejection.
5-7. `REVISION_REQUESTED -> DRAFT`, `ACCEPTED -> SUPERSEDED` and `PLAT_CERTIFIED -> DRAFT` each have multiple trigger routes; all routes are described.
8. `HARD -> CLOSED` endpoint says the unit moves `UNDER_CONTRACT -> SOLD` though a hardened unit is `HARD_CONTRACT` — prose states simply that `sale_status` becomes `SOLD`.
9. `CLOSINGS -> COMPLETED` follows the state machine (every `INCLUDED` unit `SOLD`), not the endpoint's "no `HARD` agreement remains".
10. `ERR_DUPLICATE_KEY` uses the fuller validations tuple list, not the shorter errors-catalogue list.
11. The `RELEASED -> THRESHOLD_SHORT` trigger list omits unit withdrawal although the withdraw endpoint's side effects demote both `THRESHOLD_MET` and `RELEASED` batches — the withdrawal cascade is described as reaching both.
12. `verdict_reason = NO_QUALIFYING_CONTRACTS` has no persisted field, so the empty-population fallback is stated as a `NON_WARRANTABLE` verdict on the ground of no qualifying contracts, without implying a stored field.

### 4c summary (verbatim)
160 lines. §4: one status-code paragraph (201 for the 21 resource-minting creates; 200 for all 76 others including every read/computed summary, every PATCH, the section PUT, every lifecycle transition, the posture sweep and both clock endpoints; explicitly notes no endpoint returns 204 and that the single DELETE also returns 200), then the 4-column table. §5: one `error_id` sentence then the 2-column table. Scripted verification: 97 and 50 data rows, both sequences exactly equal to the scaffold in order, every `Authorized Role(s)` cell identical in members and order to the endpoint's `roles:`, zero tokens outside the nine role names, all cell counts correct, max Description length 84 chars, zero snake_case identifiers / backticks / `cents` / `bp` / "side effect" in any Description. Roughly forty Descriptions were rewritten to strip request-body field lists and cascade/side-effect detail so readers must return to §3 to reconstruct the contract.

---

## Step 6: Generate Implementation — 2026-09-03T20:47:39.190Z

Launched as a background subagent concurrently with Step 5. Because the Step 5/6 co-launch was split across two orchestrator messages (context boundary), the impl generator could no longer be guaranteed *physical* isolation from `test_suite/`, so the prompt carried an explicit hard prohibition on reading, listing, globbing, or grepping `test_suite/`, `test_helpers/`, either design yaml, `worklog.md`, or any sibling `task_*/`. Its declared inputs were exactly `workspace/INSTRUCTION.md`, `SCAFFOLD.yaml`, `workspace/PRD.md`. The prompt also carried the chunked-append output protocol (one `cat >>` per turn, <200 lines, quoted heredoc) that this task has used since the Step 2 64k-cap loss, and the port/pid-only kill rule for smoke servers (a broad `pkill -f "python3 app.py"` would take down all ~32 concurrent pipelines on this host).

### Step 6 summary (verbatim)

All verification is complete and both smoke servers have been stopped by their own PID/port. Final report:

## Deliverable
`/home/ubuntu/github/CodingPRD/tasks/task_2576_condominium_conversion_public_offering_statement/workspace/implementation/` — Python 3 + Flask, in-memory dicts only, 4,645 lines across 30 files.

**Layout (lines):** `app.py` 85 (factory, 11 blueprints, envelope error handlers, `PORT` read here only) · `validation.py` 349 (the ordered ladder) · `store.py` 174 · `serializers.py` 132 · `errors.py` 126 (the 50 ids + statuses) · `rounding.py` 94 · `clock.py` 86 · `envelope.py` 61 · `start.sh`, `requirements.txt` (`Flask==3.0.3`).
**routes/**: `engineering.py` 341, `agreements.py` 273, `warranty.py` 267, `tenants.py` 261, `batches.py` 261, `financial.py` 247, `declaration.py` 242, `pos.py` 219, `projects.py` 118, `units.py` 99, `clock_routes.py` 40.
**services/**: `cascades.py` 259, `projects.py` 186, `sales.py` 180, `warranty.py` 116, `budgets.py` 108, `reserves.py` 100, `suitability.py` 87, `interests.py` 73, `tenants.py` 61.

## Verification
- `py_compile` on every module: **COMPILE_OK**.
- **Route coverage:** declared 97 / unique 97 / `app.url_map` 97; MISSING and EXTRA both empty.
- **Error coverage:** 50 declared ids, 50 unique, `not in catalogue: []`, `catalogue extras: []`, `declared but never raised: []`.
- **Boot contract:** `start.sh` reads `$PORT`, binds `0.0.0.0`, runs in the foreground; guarded pip install; no seeding, no SQLite/JSON/`/tmp` persistence (only `__pycache__` appears on disk).
- **Empty store after restart:** killed the first instance (pid 1343997 / port 41793), booted a fresh one on port 51909 — `conversion-projects, units, purchase-agreements, tenant-households, warranty-claims, reserve-studies, initial-budgets, public-offering-statements, suitability-assessments` all `total_count 0`, and `GET /_clock/current` back to exactly `2026-08-01T00:00:00Z`. That instance was then killed by pid too. No broad pkill was ever used.

## Six smoke phases, all clean
1–3 (earlier): full happy path — gate FAILED→FROZEN with `ERR_PROJECT_FROZEN`, plat sweep to exactly 10000 bp, POS 9 sections→EFFECTIVE, adjacency accepted / overlap refused, three OCC 412s, rescission refused at the exact deadline while hardening succeeded at the same instant, non-mutating threshold summary, release→CLOSINGS, all-sold→COMPLETED/SETTLED, warranty cap 60 %, 72 h cooldown collision refused and `end+259201s` accepted, third reopening refused, sweep closing the expired REMEDIATED claim.
4. Peer-review REJECT cascade: report→REVISION_REQUESTED, assessments INVALIDATED, gate FAILED, posture FROZEN, writes refused; `POST /revisions` correctly refused with `ERR_PROJECT_FROZEN` (it is *not* on PRD line 508's exemption list) while the exempt component PATCH reopened the report to DRAFT — the documented recovery route. CASH_FLOW study 252500 → PATCH re-derived only `percent_funded_bp`/`funding_status` (2500 UNDERFUNDED → 10000 ADEQUATE). Budget re-tiered on PATCH (500→800 bp). Assessment allocation 10587316/10587316/10590493 (single-unit residual).
5. Withdrawal/reinstatement: `[3333,3333,3334] → [4999,0,5001] → [3333,3333,3334]` byte-identical, `bp_conservation_total` 10000 throughout, plat DRAFT + `plat_revision` 1. Tenant register: notice tiers 180/360/165/360 days, assistance 900000/1125000/540000/1500000 (cap and floor exercised); ROFR EXERCISE reversed 540000 and withdrew the notice; sweep advanced VACATE_DUE + EXPIRED + claim closure; `ERR_RELOCATION_AMOUNT_MISMATCH`, identity binding both ways; relocation delta 0 at every step.
6. Material amendment: HARD→SIGNED with deadline restarted to `max(current, +5d)` and `rescission_restart_count` 1, statement AMENDMENT_FILED, project CLOSINGS→…→REGISTRATION/RESTRICTED, `ERR_POS_NOT_EFFECTIVE` on a new signing, re-conferral stamped a later `effective_at`. `ERR_PROJECT_RESTRICTED` on release (HOLDOVER household and an ACCRUED/EXPIRED household both match restricting clauses). Withdrawal over live sales: agreement VOID + escrow REFUNDED with `escrow_reconciliation_delta_cents` 0 (6000000 recv / 2000000 bal / 4000000 refunded), statement→AMENDMENT_REQUIRED, `ERR_LAST_INCLUDED_UNIT` on the final unit with the survivor at 10000 bp. Envelope/rung checks: `req_`-prefixed id, list `meta` with limit/offset/total_count/has_more, 422 `ERR_INVALID_PAGINATION`, 401 `ERR_MISSING_AUTH_HEADERS` (including an unknown role name, per PRD line 514), 403 `ERR_ROLE_NOT_PERMITTED`, 404 not-found ids.

Every apparent failure in phases 4–6 traced to a wrong expectation in my throwaway scripts (endpoint spelled `/withdraw` not `/withdrawal`, 400-vs-422 guesses, expecting OPEN posture where two restricting clauses held, expecting a qualifying-count drop that PRD line 714 does not produce since SIGNED+FUNDED still qualifies). No implementation change was needed after phase 3.

## PRD vs SCAFFOLD divergences — PRD followed in every case
1. project create posture: scaffold `OPEN` vs PRD `RESTRICTED`. 2. tenant registration `PENDING`/`NOT_ELIGIBLE` vs PRD `PRE_NOTICE`/`NOT_OWED`. 3. ROFR EXERCISE `WITHDRAWN`/`CANCELLED` vs PRD `NOTICE_WITHDRAWN`/`REVERSED`. 4. accrued relocation "reduced" vs PRD monotonic accrual. 5. warranty triage `TRIAGED_DENIED`/`ADMIT`/`DENY` vs PRD `DENIED`/`ADMISSIBLE`. 6. peer-review REJECT bumping `revision_round` vs PRD bumping it only at submit. 7. plat certification bumping `plat_revision` vs PRD bumping only on the revert edge. 8. `reported_by_unit_id` optional in scaffold, required in PRD §3.9. 9+12. `min_absolute_unit_count` required in scaffold, default 1 in PRD. 10. scaffold's `basis` query parameter on `warrantability_ratios` vs PRD's input-free read that computes and persists both bases. 11. closing side effect `UNDER_CONTRACT → SOLD` vs PRD `HARD_CONTRACT → SOLD`.

**Inference notes** (no dedicated error id exists, so the transition precondition reports): `ERR_PERCENTAGE_INTEREST_NOT_BALANCED` is evaluated pre-sweep over current `percentage_interest_bp`; PATCH state restrictions, the "no other RELEASED batch" clash, and premature warranty completion all map to `ERR_INVALID_STATE_TRANSITION`; inverted/zero-length windows fold into `ERR_BATCH_WINDOW_OVERLAP` / `ERR_REMEDIATION_WINDOW_OVERLAP` per scaffold priorities 38/39. One genuine internal PRD contradiction: line 602 pins the plat-revert edge (and its `plat_revision` bump) to a `PLAT_CERTIFIED` package, while line 610's narrative claims `plat_revision` ends "two higher" after withdraw+reinstate — I followed line 602's explicit precondition, so a reinstatement onto an already-DRAFT package leaves the counter alone. Also, rejection-cascade hop three writes `suitability_gate` FAILED unconditionally (its stated cause, "no EFFECTIVE assessment left", holds regardless) while the `DOCUMENTS_PREPARATION → SUITABILITY_REVIEW` status move fires only from that source state.

### Orchestrator verification of Step 6

Independently confirmed on disk: `workspace/implementation/` holds `app.py`, `validation.py`, `store.py`, `serializers.py`, `errors.py`, `rounding.py`, `clock.py`, `envelope.py`, `requirements.txt`, an executable `start.sh`, plus `routes/` and `services/` packages. No `results.*.json` yet (Step 7 has not run). The only non-source artifact is `__pycache__`, consistent with the no-disk-persistence claim.

Two items are carried forward for Step 7 to watch, because they are the places where the implementation resolved something the PRD left contradictory rather than merely underspecified:
- **PRD line 602 vs line 610 on `plat_revision`.** The implementation followed line 602's explicit `PLAT_CERTIFIED` precondition, so withdraw-then-reinstate onto an already-DRAFT package does not bump the counter twice. If a corner test asserts line 610's "two higher" narrative, Step 7 must adjudicate under the PRD-First protocol — a PRD that admits both readings fails unique derivability, and the test is deleted rather than the implementation bent.
- **Errors reached only by inference.** `ERR_INVALID_STATE_TRANSITION` is the catch-all the implementation uses for PATCH state restrictions, the "no other RELEASED batch" clash, and premature warranty completion; inverted/zero-length windows fold into the two overlap errors. All 50 catalogue ids are raised somewhere, but these particular mappings are the implementation's inference, not PRD prose.

---

## Step 5: Generate Unit Tests — 2026-09-03T21:00:02.552Z

(Appended after Step 6 because the two ran concurrently and Step 6 returned first; this worklog is append-only, so entries are in completion order, not step order.)

Launched as a background subagent. Inputs: `SCAFFOLD.yaml`, both design indices, `workspace/PRD.md`. Outputs mandated at the TASK ROOT (`test_helpers/`, `test_suite/`) and forbidden from creating, reading, or touching `workspace/implementation/`. Prompt carried the design-index-only contract, the verbatim `Design:` tag requirement, the chunked-append output protocol, the `TenantOccupant`/`Purchaser` own-id header rule, and the six end-of-run verification checks.

### Step 5 summary (verbatim)

Generation and verification are complete.

## Files created (task root, never under `workspace/`)

`test_helpers/` (2,025 lines): `__init__.py` 44, `api_client.py` 576, `api_errors.py` 73, `assertions.py` 162, `constants.py` 128, `factories.py` 276, `fixtures.py` 648, `test_users.py` 111, `types.py` 7.

`test_suite/` (5,834 lines, 13 files): `conftest.py` 13, `test_authorization.py` 442 (10 tests), `test_closing_batches.py` 582 (7), `test_declaration_and_units.py` 751 (15), `test_engineering_reports.py` 661 (15), `test_pagination_and_errors.py` 79 (2), `test_project_lifecycle.py` 396 (9), `test_public_offering_statement.py` 483 (6), `test_reserves_and_budget.py` 522 (9), `test_sales_and_escrow.py` 523 (7), `test_suitability.py` 289 (4), `test_tenants.py` 429 (6), `test_warranty.py` 664 (5).

## Verification (all clean)

1. Both dirs are at the task root; `workspace/` contains only `INSTRUCTION.md`, `PRD.md` and the sibling's `implementation/`, which was never read or written.
2. `python3 -m py_compile` passes on all 22 generated `.py`; `pyflakes` is clean except two intentional re-exports (`test_helpers/__init__` re-exporting `api_errors`, `conftest` re-exporting the `api` fixture).
3. `python3 -m pytest --collect-only -q` from the task root: **95 tests collected**, 0 errors.
4. Tag audit: 95 tests, each with exactly one `Design:` tag as the docstring's last line and `PRD: ` as its first; 95 distinct tags; 0 claimed twice; 0 dangling; 0 pointing at one of the 29 `excluded_because:` stubs; 0 non-stub instances missing a test.
5. `tenant_headers(tenant_household_id)` / `purchaser_headers(purchase_agreement_id)` have no default and raise on empty input; every self-resource act passes the entity's own id (`household["id"]`, `pa1["id"]`, …). The two `UNBOUND_*` constants appear only in pre-entity role-denial and clock probes.
6. No `pytest.mark.skip`, no `xfail`, no `try/except` anywhere in `test_suite/`.

## Coverage

Queue A — Difficulty, 18/18 non-stub, 0 stubs: 2 each across `boundary_precision_check`, `combinatorial_formula`, `compensating_invariant`, `cross_entity_state_dependency`, `dual_variant_calc`, `non_linear_state_machine`, `priority_pair_validation_conflict`, `resource_temporal_overlap`, `transitive_cascade`.

Queue B — Corner, 77/77 non-stub (29 stubs untouched): validations 14, state_machines 13, entities 11, calculations 9, rbac 8, endpoints 7, cross_cutting_complexity_layers 6, errors 5, consistency_model 4.

**Skipped instances: none.** Every non-stub instance had verbatim PRD coverage that uniquely derived its outcome.

## Design-recipe vs PRD conflicts (PRD followed in every case)

1. Recipes re-verify components after submission; PRD 536 auto-verifies on submit — three recipes adjusted.
2. `boundary_convention: WALL_CENTERLINE` (14 occurrences) is not a legal enum member -> `CENTERLINE`.
3. `total_unit_count: 1` (26 occurrences) violates the PRD minimum of 2 -> 2. Verified via PRD 492/496/702 that it never moves an asserted literal (only `single_investor_max_pct` reads it, and no affected test asserts it).
4. SCAFFOLD blurb "REJECT: revision_round += 1" contradicts the PRD -> the four-hop reject test asserts 1 before and after.
5. `life_safety_component_below_five_years_blocks_plat_certification` was unreachable as written -> elevator given `planned_remediation_gain_years: 1` and the gate passed via a `POST_REMEDIATION` assessment (score 92.42).
6. `create_response_detail_read_and_list_projection_agree_within_one_sequence` submitted a report with no child component -> ROOF added.
7. `peer_review_accept_supersedes_prior_accepted_sibling_report` computed `${er1_v} + 1` from a stale token -> the sibling version is re-read immediately before the trigger.
8. `pos_effectiveness_blocked_until_declaration_recorded` asserted project `REGISTRATION` pre-recording, but PRD 604/672 make recording the `DOCUMENTS_PREPARATION -> REGISTRATION` edge -> asserts `DOCUMENTS_PREPARATION`.
9. `escrow_cash_conserved_across_fund_then_rescind` prose mentions 2026-08-10 though the recipe never moves the clock -> clock stays at the default.
10. Several POSTs that mint a resource were marked `200` in recipes (notices, ROFR responses, relocation disbursements, occupancy outcomes, agreement assignments, POS deliveries, escrow deposits) -> tests assert **201** per PRD 744 and the API table.
11. `GET /declaration-packages/{id}/assessment-allocation` reads (no such endpoint) were transcribed as per-unit `GET /units/{id}` reads plus an INCLUDED-filtered count, preserving every asserted value.
12. **New:** `closing_blocked_until_assigned_batch_is_released` asserts end-state batch `SETTLED`, but PRD 724 only settles batches when the project reaches `COMPLETED`, and the same recipe asserts an unsold INCLUDED `G-2` and project `CLOSINGS` -> the test asserts the batch stays `RELEASED`.
13. **New:** `remediation_closed_interval_cooldown_and_depth_cap` triages three claims `ADMIT` on a unit its setup never sells, but PRD 730 requires the `reported_by_unit_id` unit to be `SOLD` -> the test drives J-1 through hardening/release/closing first (a second unit J-2 keeps the project in `CLOSINGS`, so no asserted literal moves).
14. Judgment call, noted for review: for the zero-length batch window (probe 5 of `closing_batch_half_open_window_adjacency_allowed`) the PRD says only that it "is rejected" and names no error; `ERR_BATCH_WINDOW_OVERLAP` is the sole error the PRD attaches to batch-window geometry (rung 5 covers field shape, not cross-field ordering), so the recipe's `ERR_BATCH_WINDOW_OVERLAP`/409 was followed.

### Orchestrator verification of Step 5

Re-ran the checks myself rather than trusting the self-report. `python3 -m pytest --collect-only -q test_suite/` -> **95 tests collected in 0.18s, 0 errors**. `Design:` tags: 95 total, 95 distinct, zero tag claimed more than once. Zero occurrences of `pytest.mark.skip`, `xfail`, or `try:` anywhere under `test_suite/`. `test_helpers/` and `test_suite/` are both at the task root; `workspace/` holds only `INSTRUCTION.md`, `PRD.md`, `implementation/` — so the memory-noted failure mode of test dirs landing under `workspace/` did not occur and no move was needed.

Conflict item 14 is the one carried into Step 7 as a live risk: the zero-length-batch-window probe asserts `ERR_BATCH_WINDOW_OVERLAP` on a rejection the PRD does not attach an error id to. Step 6 independently folded inverted/zero-length windows into the same error, so the two halves are likely to agree — but if that probe fails, it fails unique derivability (a faithful PRD reader could return a shape/constraint error instead) and the assertion must be relaxed or removed, not fixed in the implementation.

---

## Step 7: Run Tests and Iterate — 2026-09-03T21:55:00.000Z

One long-lived fix subagent owned the whole run->diagnose->fix->rerun loop. Sweeps ran as 8 concurrent rounds under `setsid nohup` with `--isolation per-test-server --timeout 120 --test-timeout 30` and no `--api-url`.

### Step 7 summary (verbatim)

All 8 rounds green. Here is the final report.

## Summary

**Outcome: 95/95 in all 8 rounds. Zero tests deleted (95 -> 95). Zero implementation files modified — every fix is test-side.**

### Iterations

| Iter | Rounds green / 8 | Per-round | Union failures |
|---|---|---|---|
| 1 | 0/8 | 62/95 | 33 (all 8/8) |
| 2 | 0/8 | 88/95 | 7 (all 8/8) |
| 3 | 0/8 | 93/95 | 2 (all 8/8) |
| 4 | **8/8** | **95/95** | **0** |

Final literal per-round `passed`/`total`: `results.1`–`results.8` each `95 / 95`, `failed=0`, `errors=0`.

### Deleted tests
**None.** No test failed both STEP 1a coverage and STEP 1b unique derivability outright; the three that carried an underivable *assertion* were repaired by STEP 1c split (keep the covered assertion, drop or relax the uncovered one), not deleted.

### Test-side fixes (iterations 2–4; earlier iteration-1 fixes listed after)

1. **`test_engineering_reports.py::test_report_revision_cycle_...` + `test_project_lifecycle.py::test_project_posture_rederived_...`** — both drove the `REVISION_REQUESTED -> DRAFT` reopen through `POST /engineering-reports/{id}/revisions` on a FROZEN project. **STEP 1c split** on a genuine PRD tension. PRD §3.1: *"A `FROZEN` posture rejects every write request against the project's graph with `ERR_PROJECT_FROZEN` (HTTP 409), with a pinned exemption list: … adding a major component, adjusting a major component's engineering inputs, submitting a report, recording a peer-review decision, creating a suitability assessment…"* — the explicit revision request is **not** named. PRD §3.2: *"The `LicensedEngineer` reopens it … either by explicitly requesting a revision … or, **equivalently**, by adjusting any child component."* Two readings are articulable: (A) the list is pinned and closed, so the explicit route is refused (the implementation's reading); (B) "equivalently" + *"That exemption list is what makes a frozen project recoverable"* extends the exemption. **BRANCH-ASYMMETRIC / ERROR-PRECEDENCE SILENCE.** Repair: drive the reopen through the route the exemption list *does* name, which PRD §3.2 says performs the identical edge — *"If instead the parent report was in `status` `REVISION_REQUESTED`, the edit reopens the drafting cycle and the report moves `REVISION_REQUESTED -> DRAFT`."* Every substantive assertion (revision_round unchanged by the reopen, counters zeroed, resubmit -> 2) is retained and now passes under **both** readings. Redundant `verify_component` calls were dropped because PRD §3.2 submission *"sets `verification_status` to `VERIFIED` on every child major component"* — and `POST /major-components/{id}/verification` is likewise absent from the pinned list. This is also the suite's own established pattern: the already-passing `test_frozen_posture_blocks_non_exempt_writes_but_not_exempt_ones` reopens via `patch_component`.

2. **`test_warranty.py`** (2 tests, 5 call sites) — `claim_payload` omitted `reported_by_unit_id`, yielding 422. PRD §3.8: *"A unit owner's claim is filed against the project by naming the `major_component_id` …, **the `reported_by_unit_id` whose owner reported it**, a non-empty `defect_description` … and a `claimed_cost_cents` estimate of at least 0."* A required creation input; the helper made it optional. Test-helper bug.

3. **`test_public_offering_statement.py::test_put_pos_section_upserts_...`** — asserted the section list totals 1. PRD §3.6: *"**nine child sections are synthesized in the same act**."* Corrected to 9 rows, with a `content_status=COMPLETE` filter asserting 1 to preserve the "upserts one row" intent.

4. **`test_public_offering_statement.py::test_material_pos_amendment_cascade_...`** — asserted `presale_sold_pct == 0.00` immediately after the material-amendment cascade; got the stale `100.00`. **COMPUTED-FIELD SILENCE.** The PRD names exactly what refreshes this persisted projection — the explicit batch threshold evaluation (*"The project's `presale_sold_pct` is recomputed as well"*) and the warrantability read (*"that read is not passive: it runs the ratio computation under **both** bases and persists both verdicts on the project"*) — and the amendment cascade (§3.6 hops one–four) is not among them. **STEP 1c split:** the assertion moved to after the warrantability read the PRD does declare, where 0.00 is fully derivable (sole `INCLUDED` unit back at `UNDER_CONTRACT`, numerator 0 / denominator 1).

5. **`test_declaration_and_units.py::test_plat_certification_with_an_empty_included_set_is_refused`** — two defects. (a) Demanded `ERR_PERCENTAGE_INTEREST_NOT_BALANCED` for an empty `INCLUDED` set. PRD §3.4 lists *"the package must have at least one child unit whose `declaration_status` is `INCLUDED`"* as its own precondition, ahead of and separate from the balance check, and assigns it **no error id**. **ERROR PRECEDENCE SILENCE** -> relaxed to `validate_error_is_one_of(["ERR_PERCENTAGE_INTEREST_NOT_BALANCED", "ERR_INVALID_STATE_TRANSITION"])` with the 409 kept hard. (b) Its control path declared a lone unit at 5000 bp and expected certification to succeed; PRD §3.4 states *"for the plat to certify, the sum of `base_percentage_interest_bp` over all sibling units must itself total 10000."* Fixture bug — the unit is now raised to 10000 bp (and the intermediate 5000 state is asserted to be refused).

6. **`test_closing_batches.py::test_presale_pct_inclusive_at_exact_threshold_equality`** — (a) `min_presale_threshold_pct` sent as the strings `"50.01"`/`"49.99"` -> 422. PRD §3.7: *"a `min_presale_threshold_pct` between 0.00 and 100.00 inclusive carried to 2 decimal places"* — a number; rung 5 requires types to match. (b) Expected `ERR_PRESALE_THRESHOLD_NOT_MET` on releasing a `THRESHOLD_SHORT` batch; got `ERR_PROJECT_RESTRICTED`. PRD §2 rung 7: *"The project's derived posture is consulted **first**: … a batch release attempted on a project whose posture is `RESTRICTED` rather than `OPEN` is rejected with `ERR_PROJECT_RESTRICTED`."* A `THRESHOLD_SHORT` batch is itself one of the eight RESTRICTED clauses, so the posture gate always wins. Corrected (this precedence is independently asserted by the already-passing `test_batch_release_is_escrow_agent_only_and_still_blocked_by_restricted_posture`).

7. **`test_closing_batches.py::test_closing_blocked_until_assigned_batch_is_released`** — `assert 5 == 4`: compared the post-refusal agreement version against a snapshot taken *before* an intervening legitimate write. PRD §2.4: *"**Each entity touched by such a cascade has its own `updated_at` refreshed … and its own `version` incremented by one**, whether it was the resource named in the request path or a record reached indirectly."* Batch assignment *"sets the agreement's `closing_batch_id`"*, so the bump is correct. Replaced with `assert_no_write` against the state captured immediately before the refused request.

*Iteration-1 fixes (pre-existing context, all test-side):* `assert_instant` normalized to compare instants rather than fractional-digit spellings (~19 tests; the PRD pins a rendering only for `created_at`/`updated_at`/`api_request_timestamp`); three `submitted_by_user_id is None` pre-state assertions removed (DEFAULT-VALUE SILENCE — §3.2 makes it a creation *input*); 7 request-side `"50.00"` strings -> numbers; `composite_score` -> `score` (§3.3); `included_unit_count` read from the project not the package (§3.1/§3.5); `response_type` read top-level not inside `meta` (§2.2); pre-certification `allocated_bp_total` 0 (§3.5: *"The sweep runs whenever a plat is certified and whenever a unit is withdrawn or reinstated"*); section total 0 -> 9.

### Implementation fixes
**None.** Every failure resolved to test-side coverage/derivability/consistency defects. In each disputed case the implementation's behaviour traced to a verbatim PRD sentence (the pinned exemption list, `reported_by_unit_id` as a named input, the base-sum-totals-10000 certification precondition, rung 7's posture-first ordering, §2.4's per-record version bumps, the declared refresh points for `presale_sold_pct`). Confirmed by mtime: the last write under `workspace/implementation/` is 20:33:09, from the implementation generator; all of my edits are 21:26 or later and all land in `test_suite/` or `test_helpers/`.

### Failures attributed to host load or sweep reaping
**None.** Across all four iterations every failure reproduced in **8/8 rounds** with identical error text, and every round of every iteration reported an identical `passed`/`total`. No timeouts, no connection-refused, no `errors` (as distinct from `failed`) in any round, and no server log ending in `Terminated`. There was no non-determinism to attribute to contention, and no re-run was needed to clear anything. All sweeps ran under `setsid nohup` with the runner allocating its own port per round; diagnosis was taken only from the per-round `results.$i.json`, never from `sweep.log`.

### Orchestrator verification of Step 7

Per my standing note that a Step 7 subagent can claim a clean sweep while leaving no artifacts behind, I read the eight result files myself rather than accepting the claim. All eight exist (`results.1.json` … `results.8.json`, ~28.7 KB each, all written 21:52) and every one reports literally `passed=95, failed=0, errors=0, total=95, skipped=0`. `pytest --collect-only -q test_suite/` still collects **95 tests**, so the suite was neither thinned nor left uncollectable — consistent with the zero-deletions claim. The newest file anywhere under `workspace/implementation/` is `app.py` at 20:33, predating every Step 7 edit, which independently confirms zero implementation changes.

Because Step 7 made numerous `test_suite/` and `test_helpers/` fixes, the Step 8 skip condition (0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes) is NOT met. Step 8 runs.

---

## Step 8: Finalize PRD — align documentation to implementation — 2026-09-03T22:12:00.000Z

Step 8 ran because the skip condition (0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes) was not met — Step 7 made no implementation change but many test-side ones. The Step 7 worklog entry above was inlined verbatim as `<step_7_diff>`. The subagent was told that a pure fixture or type-coercion bug must produce no PRD edit, was given the NO-NEW-MISMATCH rule with the mandatory per-edit global implementation search, and was required to work by `cp` + surgical Edit calls (never re-emitting the 901-line document) to stay clear of the 64k output cap.

### Step 8 summary (verbatim)

All edits applied and verified.

## Line counts
- `PRD.md` 901 lines -> `PRD_FINALIZED.md` 905 lines (**+4 lines, +0.44%**); 7 diff hunks, all inline single-paragraph revisions.

## Changes (one bullet each)

1. **§2.5 (common properties)** — insert — every instant-valued response field (all `*_at`, plus `inspection_date`/`tenancy_start_date`) renders in the same three-fractional-digit ISO format as `created_at`/`updated_at`, nulls as JSON `null`; clock's `current_utc` excepted — `serializers.py:130-138` (`_value`/`dump` -> `clock.format_instant`), `clock.py:69-76`.
2. **§3.1 (What the posture gates)** — revise — exemption list declared **closed and exhaustive** and trimmed to the nine writes the impl actually exempts; explicitly names the refused set (explicit revision request, per-component verification, project intake `PATCH`, warranty filing and all four warranty transitions); adds that batch release, gated on posture being exactly `OPEN`, answers `ERR_PROJECT_RESTRICTED` even on a `FROZEN` project — `validation.py:309-321`, `routes/engineering.py:154,250`, `routes/warranty.py:54,132,173,202,225`, `routes/projects.py:79`, `routes/batches.py:218`.
3. **§3.1 (The logical clock)** — insert — both clock endpoints render `current_utc` in whole seconds when the instant has no fractional part, else three digits — `routes/clock_routes.py:21-27,30-40`.
4. **§3.2 (Closing the revision cycle)** — insert — the two reopen routes are effect-equivalent but not availability-equivalent: `POST /engineering-reports/{id}/revisions` is off the exemption list and answers `ERR_PROJECT_FROZEN` while the derived posture reads `FROZEN` (posture gate before state precondition); the component-adjust route is the working one — `routes/engineering.py:148-158` vs `217-240`, `services/projects.py:107`.
5. **§3.4 (Certifying the plat)** — insert — the empty-`INCLUDED` precondition is refused with `ERR_INVALID_STATE_TRANSITION` (409), explicitly not `ERR_NO_INCLUDED_UNITS` / `ERR_PERCENTAGE_INTEREST_NOT_BALANCED`; the six preconditions are evaluated in §2's ladder order, not list order — `routes/declaration.py:117-131`.
6. **§3.7 (material amendment cascade)** — insert — the cascade does not refresh the project-level warrantability projections (`presale_sold_pct` included); those refresh only at a batch threshold evaluation, the five agreement events of §3.8, and the warrantability read; hop three's batch-level `presale_pct` *is* recomputed — `services/cascades.py:174-215` (no `recompute_warrantability`), `services/projects.py:53-98` (`sync` doesn't touch it), `routes/batches.py:203-206`, `services/sales.py:145-180`.
7. **§3.8 (Lender warrantability)** — insert — the warrantability read persists its figures but neither bumps `version` nor refreshes `updated_at` — `routes/projects.py:111-118` (`bump=False`), `services/sales.py:176-180`.

## Per-edit pre-edit search log
- **Edit 1** — (a) rendering of instant-valued response fields. (b) `serializers.py` FIELDS (all 14 entity field lists enumerated for datetime members), `_value`, `dump`; `clock.format_instant`; `envelope._meta`; the two computed reads that build ad-hoc payloads (`routes/warranty.py:242-267`, `routes/batches.py:247-261`). (c) narrowed to "every `*_at` field … plus `inspection_date` and `tenancy_start_date`" after confirming those are the only two non-`*_at` datetimes, and carved out `current_utc` explicitly rather than claiming a universal format.
- **Edit 2** — (a) the FROZEN exemption list / which error each posture gate reports. (b) grepped every `gate_not_frozen` and `gate_posture_open` callsite (48 sites across all 11 route modules) plus `validation.py:309-321`; read `routes/engineering.py` and `routes/warranty.py` in full; checked `routes/projects.py` create/patch/recalculation and `routes/clock_routes.py`. (c) removed the warranty clause from the exemption list (impl gates all five warranty writes), added the un-exempt writes the impl gates, and softened the "every write -> `ERR_PROJECT_FROZEN`" universal with the release/`gate_posture_open` exception.
- **Edit 3** — (a) `current_utc` rendering. (b) `routes/clock_routes.py` (`_render`, both endpoints), `clock.BOOT_INSTANT`, `clock.format_instant`; confirmed no other producer of `current_utc`. (c) scoped to "both clock endpoints" so no claim leaks onto entity fields.
- **Edit 4** — (a) the `REVISION_REQUESTED -> DRAFT` reopen. (b) `routes/engineering.py:148-158` (revise, gate before `require_state`), `217-240` (`patch_component`, both `ACCEPTED` and `REVISION_REQUESTED` branches, no gate), `services/cascades.py:74-103` (rejection sets the freezing clause + recomputes posture), `services/projects.py:101-147`. (c) said "for as long as the project's derived `posture` still reads `FROZEN`" rather than "always", to avoid asserting the endpoint is unreachable.
- **Edit 5** — (a) the empty-`INCLUDED` precondition and its error id. (b) `routes/declaration.py:43-46,117-137,140-175`, `services/interests.py:68-73`, `routes/units.py:70-89` (`ERR_LAST_INCLUDED_UNIT`), `routes/batches.py:187-208` (`ERR_NO_INCLUDED_UNITS`), `errors.py:65-66,119-120`, §2 rungs 7–8. (c) restricted the disambiguation to certification and named where `ERR_NO_INCLUDED_UNITS` does belong, so the recording path (which reaches only `ERR_PERCENTAGE_INTEREST_NOT_BALANCED`) is not mis-described.
- **Edit 6** — (a) what refreshes the project's persisted warrantability projections, `presale_sold_pct` above all. (b) grepped all `presale_sold_pct` and `recompute_warrantability` writes/callsites: `services/projects.py:45` (creation default), `routes/batches.py:203-206`, `routes/agreements.py:76,148,218,270`, `services/cascades.py:237`, `routes/projects.py:116-117`; read `services/cascades.py:174-215` and `services/projects.py:53-98` to confirm neither `file_amendment` nor `sync` touches them. (c) added the closing sentence distinguishing batch-level `presale_pct` (which `demote_batches` -> `write_batch_counters` does refresh) from the project-level fields, and listed the threshold evaluation alongside §3.8's events rather than saying "only §3.8".
- **Edit 7** — (a) side effects of the warrantability read. (b) `routes/projects.py:111-118`, `services/sales.py:145-180` (`bump` flag), `store.touch`; compared with the other computed reads (`routes/warranty.py:252` calls `sync`, which *can* touch; `routes/batches.py:253` writes nothing). (c) scoped strictly to the warrantability read — no general "reads never bump" claim, since `warranty-summary`'s `sync` can bump.

## `<step_7_diff>` items deliberately NOT patched
- **Item 2 (`reported_by_unit_id`)** — §3.8 already names it as a required creation input; pure test-helper bug.
- **Item 3 (nine sections synthesized)** — §3.6 already says nine sections are synthesized in the same act.
- **Item 5b (base bp must total 10000)** — §3.4 already states the operative precondition as `allocated_bp_total` recomputed over the `INCLUDED` set equalling 10000, which is exactly `interests.allocated_total`; fixture bug.
- **Item 6a (`min_presale_threshold_pct` type)** — §3.7 already declares it a number; rung 5 already requires type match.
- **Item 6b (`ERR_PROJECT_RESTRICTED` beats `ERR_PRESALE_THRESHOLD_NOT_MET`)** — §2 rung 7 already puts the posture gate above rung 8; only the FROZEN-on-release nuance needed pinning (folded into edit 2).
- **Item 7 (agreement `version` bump on batch assignment)** — §2.4/§2.5 already pin per-record bumps for cascade-touched records; snapshot bug.
- **Iteration-1 items** (`submitted_by_user_id` as creation input, `score` naming, `included_unit_count` on the project, top-level `response_type`, pre-certification `allocated_bp_total` 0, section total 9, request-side numeric percentages) — each already stated verbatim in PRD.md.

## Verification
`diff PRD.md PRD_FINALIZED.md`: 7 hunks, all in-place paragraph revisions, no structural change. §4 = 97 data rows in both; §5 = 50 data rows in both; both files end on the same real boundary, `| `ERR_PRESALE_THRESHOLD_NOT_MET` | 409 |`.

### Orchestrator verification of Step 8

Checked independently: `PRD.md` 901 lines -> `PRD_FINALIZED.md` 905 lines; `cmp` says the two files DIFFER (so the copy was genuinely edited, not passed through); `diff` yields exactly 7 hunks; §4 has 97 data rows and §5 has 50 data rows in the finalized file; and the tail still ends on `| ERR_PRESALE_THRESHOLD_NOT_MET | 409 |`, a real section boundary, so nothing was truncated.

---

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-03T23:40:00.000Z

Step 9 always runs. Per my standing note that a single-agent Step 9 can silently no-op and leave `PRD_COMPLETED.md` byte-identical to its input, I split the scan into **three sequential file-partitioned passes** over one shared output file. Partition boundaries were drawn so that no pass had to hold more than a third of the 4,645-line implementation while editing a ~1000-line document, and each pass was fenced out of the other passes' PRD sections with any cross-section finding routed to an explicit handoff list instead of being edited.

- **Pass 1** — cross-cutting layer: `app.py`, `envelope.py`, `store.py`, `serializers.py`, `errors.py`, `rounding.py`, `clock.py`, `validation.py`, `routes/clock_routes.py`, `start.sh`. PRD scope §1, §2.1–§2.9, §4 prose, §5. Created `PRD_COMPLETED.md` from `PRD_FINALIZED.md`.
- **Pass 2** — front half of the domain: `routes/{projects,engineering,declaration,units,financial}.py`, `services/{projects,suitability,reserves,budgets,interests}.py`, plus the peer-review-rejection cascade. PRD scope §3.1–§3.5.
- **Pass 3** — back half: `routes/{pos,tenants,agreements,batches,warranty}.py`, `services/{sales,tenants,warranty}.py`, plus the material-amendment and unit-withdrawal cascades. PRD scope §3.6–§3.9, plus one authorized carve-out in §2.6 rung 2 inherited from pass 2.

### Pass 1 summary (verbatim)

Pass 1 complete. `PRD_COMPLETED.md` created from `PRD_FINALIZED.md` and patched in the cross-cutting layer only.

**Line/char delta:** 905 -> 992 lines; 167,434 -> 175,906 chars (+8,472). 20 diff hunks, all mine.

**Counts:** 17 ambiguity-pins, 4 mismatch-revisions (21 total edits across 20 hunks).

**Changes**
- §2.1 — insert — ambiguity — auth headers: whitespace-only rejected, role match exact/case-sensitive, `X-User-ID` otherwise unconstrained and not checked against any user registry — `validation.py:39-48`
- §2.1 — revise — mismatch — `LenderUnderwriter` "may not mutate any resource" was false: it is on the clock-set role list; narrowed to the fourteen resources with the clock named as the exception — `routes/clock_routes.py:16-17`
- §2.1 — revise — mismatch — entity-backed ownership was described as comparing "any resource that references a TenantHousehold/PurchaseAgreement"; impl only compares the *path* identifier, and only on 4 endpoints (single-household read, rofr-response, single-agreement read, rescission); collection reads are not narrowed — `validation.py:60-64`, `routes/tenants.py:98-121`, `routes/agreements.py:95-119`
- §2.1 — insert — ambiguity — identity comparison precedes existence resolution, so mismatch outranks 404 — `validation.py:62`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` -> `ERR_INVALID_PAGINATION`; empty `?limit=`/`?offset=` treated as omitted and defaulted — `validation.py:270-291`
- §2.3 — insert — ambiguity — `created_at` ties broken by mint order (clock is frozen, so ties are the norm) — `store.py:92-98`
- §2.3 — revise — mismatch — "Single-resource responses omit all four" was incomplete: the assessment-allocation array read also omits the four — `envelope.py:29-39`, `routes/declaration.py:242`
- §2.3 — insert — ambiguity — filter semantics: absent/empty not applied, exact match, no-match yields empty page, unknown params and unparseable boolean values ignored — `validation.py:324-349`
- §2.4 — insert — ambiguity — clock is set absolutely, backwards moves accepted, already-stamped instants unaffected — `clock.py:24-25`
- §2.4 — insert — ambiguity — envelope `api_request_timestamp` is the logical clock reading, not wall-clock — `envelope.py:17-21`
- §2.5 — insert — ambiguity — nothing seeded at boot; restart empties all fourteen maps and resets the clock — `store.py:1-6,13-27`
- §2.5 — insert — ambiguity — response key order (`id`, domain fields, `created_at`/`updated_at`/`version`), unset domain fields present as `null`, timestamps take the clock reading — `serializers.py:121-128`
- §2.5 — insert — ambiguity — one `version` bump per record per request (not per write); a record created by the request stays at 1 — `store.py:52-89`, `app.py:43-46`
- §2.6 rung 3 — insert — ambiguity — body identifier that is absent/null/empty/non-string is a rung-5 `ERR_INVALID_REQUEST`, not a 404; wrong-family identifier reports the expected family's not-found — `validation.py:74-80,153-161`
- §2.6 rung 5 — insert — ambiguity — empty body read as `{}`, non-object/unparseable body -> 422, undeclared fields ignored, omitted optional takes default or leaves value untouched, blank strings rejected, strict bool/int typing, datetime grammar with `Z`/offset/no-zone all accepted and normalised to UTC — `validation.py:190-267`, `clock.py:11-67`
- §2.6 rung 7 — revise — mismatch — batch release requires posture exactly `OPEN`, so `FROZEN` also yields `ERR_PROJECT_RESTRICTED` (release never calls the frozen gate) — `validation.py:314-316`, `routes/batches.py:218`
- §2.6 — insert — ambiguity — unrouted path -> 404 and bad method -> 405, both with `error_id` `ERR_INVALID_REQUEST`, decided before rung 1 (no headers needed); trailing slash tolerated — `app.py:37,53-62` (verified live via test client)
- §2.7 — insert — ambiguity — version fields on other endpoints are ignored undeclared fields; all four are required integers; three accept any integer (stale at rung 6) while `expected_engineering_report_version` has minimum 0 so negatives fail at rung 5 — `validation.py:302-304`, `routes/engineering.py:280`, `routes/agreements.py:42`, `routes/batches.py:133`, `routes/financial.py:135`
- §2.8 — insert — ambiguity — two-decimal percentages are JSON numbers, so 33.30 renders `33.3` — `serializers.py:113-118`, `rounding.py:46-60`
- §2.8 — revise — mismatch — "the three reconciliation deltas … computed by integer subtraction": there are two delta fields plus `bp_conservation_total`, which is a sum — `serializers.py:17-19`
- §4 prose — revise — mismatch — envelope has no `success` flag; replaced with `meta` + `response_type` discriminator — `envelope.py:24-48`

**§2.2 note:** `envelope.py` does **not** contradict the shared boilerplate (meta keys, `response_type` object/array/error, `data`, error-meta restricted to the two keys all match). Left byte-identical. The only envelope-related falsehood was the `success` flag claim in §4 prose, which I fixed.

**§5:** no edits. All 50 ids and statuses match `errors.py` exactly (scripted comparison: 50/50, zero diffs). One caveat worth knowing: `ERR_INVALID_REQUEST` is catalogued 422 and that is correct for the ladder, but the routing handlers reuse that id with 404/405; I pinned that in §2.6 rather than touching the table.

**§4 table:** no edits needed. Scripted comparison of Flask's `url_map` (97 rules) against the 97 rows plus AST-extracted `authorize()` role lists: every method/path and every authorized-role set matches exactly. The 201-vs-200 prose list also matches (21 endpoints return 201, exactly the 21 named).

**HANDOFF TO LATER PASSES**
- §3.1 already pins the clock's whole-second rendering exactly as `routes/clock_routes.py:21-26` does — no action, just don't "fix" it.
- §3.x warranty summary: `routes/warranty.py:246-247` reads `window_start_at`/`window_end_at` straight from `request.args` instead of the declared datetime ladder, so a malformed window there does not go through rung-5 datetime validation. Whoever owns §3.9 should check what the PRD promises for that computed read.
- Most money arithmetic does **not** use `rounding.half_up_cents`/`ceiling_cents`/`half_up_bp`/`truncate_bp`; those are effectively dead. The real paths hold exact `Fraction`s and round once via `rounding.half_up_frac`/`ceiling_frac`/`pct2_frac` (`services/budgets.py:46,60,78`, `services/reserves.py:32,44,67,76`, `services/interests.py:36`, `services/tenants.py:54,58`, `services/warranty.py:38,51`, `services/suitability.py`). The results agree with §2.8's stated rounding modes, so I changed nothing, but §3 authors should verify each per-step rounding claim against the `Fraction` code rather than against `rounding.py`'s cent helpers.
- `services/sales.py:10` is the only user of `rounding.ratio_pct`, whose zero-denominator branch returns `0.00`; §3.8/§3.9 owners should confirm the PRD says 0.00 (not null) wherever that denominator can be zero without `ERR_NO_INCLUDED_UNITS` intervening.

### Pass 2 summary (verbatim)

All verification checks pass. Here is my report.

## PASS 2 COMPLETE

**File size:** 992 lines / 175,906 chars -> **992 lines / 186,129 chars** (all edits were in-paragraph; §3 paragraphs are single lines, so no line count change).

**Counts:** 22 ambiguity-pins, 8 mismatch-revisions (30 changes, landing as 28 diff hunks — two pairs merged onto the same paragraph line).

### Changes

**§3.1**
- insert — mismatch — segregation of duties cannot outrun existence: a peer-review decision on an unresolvable report answers `ERR_ENGINEERING_ARTIFACT_NOT_FOUND` even for the submitting engineer; once resolved it does precede body shape and the `SUBMITTED` precondition — `routes/engineering.py:118-119`, `validation.py:67-69`
- revise — ambiguity — sweep step four refreshes every §2.9 aggregate (incl. the two reconciliation deltas the derivation reads) *before* deriving, and stamps `last_posture_recalculated_at` **unconditionally** (`force=True`) — `services/projects.py:184-185`, `135-146`
- insert — ambiguity — adjusting a component does not re-derive the posture, so the stored `posture` still reads `FROZEN` until the next recomputation — `routes/engineering.py:236-239`

**§3.2**
- revise — ambiguity — `report_label` <=200 chars; `inspection_date` is a full ISO 8601 UTC instant, never clock-checked; `reviewed_by_user_id` null at creation — `routes/engineering.py:48-60`
- insert — mismatch — **both** report counters are taken over `VERIFIED` children alone, so adding a component (which arrives `UNVERIFIED`) moves neither counter and does not bump the report's `version` — `services/cascades.py:15-29`
- insert — mismatch — `patch_component`'s `ACCEPTED -> SUPERSEDED` leaves the report's assessments at `EFFECTIVE` and `suitability_score` untouched (only the gate resets); the `REVISION_REQUESTED` branch touches the project not at all — `routes/engineering.py:229-239`
- insert — ambiguity — body `reviewed_by_user_id` is required but discarded (acting header wins); `review_note` never persisted or exposed — `routes/engineering.py:121-132`, `serializers.py:28-33`
- revise — ambiguity — acceptance touches the project row not at all: not gate, status, posture or version — `routes/engineering.py:127-142`
- revise — mismatch — rejection hop three: gate/score writes are unconditional; the `DOCUMENTS_PREPARATION -> SUITABILITY_REVIEW` move is a silent no-op elsewhere, not a precondition, and assessment-invalidation is not checked — `services/cascades.py:93-97`
- insert — ambiguity — `revision_note` validated then discarded — `routes/engineering.py:153`

**§3.3**
- revise — ambiguity — no precondition constrains the report's `status`; an assessment may be created against `DRAFT`/`SUBMITTED`/`ACCEPTED`/`REVISION_REQUESTED`/`SUPERSEDED` alike — `routes/engineering.py:273-289`
- revise — mismatch — replaced "always mirror the latest assessment that is not `SUPERSEDED`" with the actual write-time semantics: the pair is never re-derived, and moves via exactly three routes (assessment creation; the rejection cascade; and the gate-only `UNEVALUATED` reset when a component of an `ACCEPTED` report is adjusted) — `routes/engineering.py:262-263`, `233`, `services/cascades.py:93-94`
- revise — mismatch — "`POST_REMEDIATION` yields a strictly higher score" was a false universal; now "never lower", with the three cases the clamps absorb (factor already clamped to 1 at/above the horizon; floored difference already 0; zero cost weight) — `services/suitability.py:61-70`

**§3.4**
- revise — mismatch — the certification balance test sums the **effective** `percentage_interest_bp` over `INCLUDED` units (withdrawn excluded), not `base_percentage_interest_bp` over all siblings; they coincide only before any sweep — `services/interests.py:68-73`, `routes/declaration.py:43-45`
- revise — ambiguity — `declaration_text_ref`/`bylaws_text_ref` <=200, `unit_number` <=100 — `routes/declaration.py:53-54,194`
- insert — ambiguity — the plat revert fires only on a *genuine* basis change, and a basis change on a package with `allocated_bp_total` 0 re-seeds the unit's effective interest on the spot; the adjustment never runs a sweep — `routes/units.py:53-66`
- revise — ambiguity — the sweep writes unit interests and `allocated_bp_total` only where the value differs (so a no-op sweep bumps no `version`), and `bp_conservation_total` is written by the following aggregate refresh over the *project's* `INCLUDED` units — `services/interests.py:20-64`, `services/projects.py:77`
- revise — ambiguity — the empty-`INCLUDED` branch zeroes `allocated_bp_total` directly; `bp_conservation_total` follows via the refresh — `services/interests.py:26-31`
- revise — ambiguity — certification effect order: status/version, then sweep, then aggregate refresh + posture recompute; the balance test reads pre-sweep values — `routes/declaration.py:122-136`
- insert — ambiguity — pinned rejection order for recording: FROZEN -> `PLAT_CERTIFIED` -> un-noticed household -> `ERR_RESERVE_STUDY_NOT_ADOPTED` -> life-safety -> balance — `routes/declaration.py:145-163`
- insert — ambiguity — recording's project `status` move is conditional and silent; both instant stamps, the project `version` bump and the posture recompute are unconditional — `routes/declaration.py:164-174`
- revise — ambiguity — `withdrawal_reason` <=500, null initially, and omission leaves the stored value rather than nulling it — `routes/units.py:76-77`, `services/cascades.py:129-130`
- revise — ambiguity — reinstatement also re-runs the §3.5 assessment allocation and the posture recompute, and does **not** clear `withdrawal_reason` — `services/cascades.py:161-166`

**§3.5**
- revise — mismatch — the referenced report's `status` is **not** a precondition of commissioning a study; only the `VERIFIED`-population gate is, so a `DRAFT` or `SUPERSEDED` report is accepted — `routes/financial.py:26-43`
- insert — ambiguity — adjusting `opening_reserve_balance_cents` re-derives *only* `percent_funded_bp`/`funding_status`; `fully_funded_balance_cents` and `recommended_annual_contribution_cents` stay as commissioned — decisive for `CASH_FLOW_METHOD`, whose formula subtracts that balance — `routes/financial.py:109-118`
- revise — ambiguity — `fiscal_year_label` <=100 — `routes/financial.py:133`
- insert — ambiguity — `patch_budget` re-copies the study figure, carries no version guard, and does not bump the project — `routes/financial.py:203-218`
- insert — ambiguity — the withdraw/reinstate re-allocation targets the project's most recently created `DRAFT`-or-`ADOPTED` budget (nothing if none), rewrites only `assessment_income_cents`/`developer_deficit_funding_cents`/`developer_subsidy_flag`, and re-derives `ADOPTED` budgets too — `services/budgets.py:92-108`
- insert — ambiguity — the package `assessment-allocation` read returns the `INCLUDED` units, `created_at` ascending, with no pagination fields — `routes/declaration.py:236-242`, `envelope.py:29-39`
- revise — ambiguity — on adoption the outgoing study is superseded only if it is a *different* study from the incoming budget's (and never re-written if already `SUPERSEDED`) — `routes/financial.py:229-246`

### Verdict on the rounding lead

I verified every per-step rounding claim against the `Fraction` code, not `rounding.py`'s cent helpers.

- **§3.3 — matches, no change.** Weights and contributions are exact `Fraction`s accumulated with no intermediate rounding; the cap is applied to the raw `Fraction` before any rounding; `pct2_frac(raw * 100)` rounds half-up to two decimals exactly once. `services/suitability.py:54-81`.
- **§3.4 — matches, no change.** The sweep is genuinely truncate-then-distribute on exact `Fraction`s (`raw.numerator // raw.denominator`), and the tie ladder is `(-fraction, -base_bp, (created_at, _seq))` exactly as written. `services/interests.py:36-53`. (`rounding.truncate_bp` is indeed unused.)
- **§3.5 — matches, no change to any rounding claim.** All four "round before summation" / CEILING claims are correct: `fully_funded_balance` half-ups each component's `Fraction` share then sums (`reserves.py:32-37`); `component_method_annual` takes `ceiling_frac` per component then sums (`44-50`); `cash_flow_annual` takes `ceiling_frac` per *year* then maxes (`64-70`); `percent_funded` half-ups once (`76-77`); the management fee half-ups once (`budgets.py:77-79`); the assessment allocation half-ups per unit, sums, hands the whole residual to one unit, then rounds the monthly amount half-up *again* from the already-rounded annual (`budgets.py:46-65`). I also re-checked §3.5's worked example (100003 cents over 3333/3333/3334 bp -> 33331/33331/33341, remainder 0) — arithmetically correct.

### Verdict on Step 8's §3.1 and §3.2 edits

**Both still correct; I re-verified rather than re-litigated.**
- §3.1's FROZEN exemption list: `gate_not_frozen` is absent from exactly `clock_routes`, project create, posture recalculation, report create, component create, component patch, report submit, peer-review decision and assessment create — the nine exempt writes named. It *is* present on `revise_report` (`engineering.py:154`), `verify_component` (`:250`), `patch_project` (`projects.py:79`) and the warranty routes, so the named refused set is right. Batch release calls `gate_posture_open` (`validation.py:314-316`), which reports `ERR_PROJECT_RESTRICTED` for any non-`OPEN` posture including `FROZEN` — correct.
- §3.2's two-reopen-routes paragraph: `revise_report` gates on FROZEN while `patch_component` does not, so the availability asymmetry is real, and the posture gate does precede the report's own state precondition in `revise_report`. Correct.

### HANDOFF TO PASS 3
- **§3.8 warrantability** — `GET /conversion-projects/{id}/warrantability-summary` is not a passive read: it runs `sales.recompute_warrantability` on *both* the contract and closed bases and persists both verdicts, with `bump=False` so no `version` moves — `routes/projects.py:111-118`. §3.8 should pin this.
- **§3.4 contains the unit-withdrawal cascade paragraphs**, which your brief assigns to you via `cascades.py` but whose prose sits in *my* section. I read `cascades.py:126-166` and pinned what routes/units.py exposes (last-included guard, `withdrawal_reason` semantics, reinstatement's extra effects). Two things I deliberately left alone in case they are yours: (a) PRD hop three describes escrow as an explicit `+/-deposit_cents` adjustment, whereas impl relies on `projects.sync()` recomputing the totals from the agreements (`cascades.py:147`, `projects.py:64-93`) — effect-identical, so I judged it not worth touching; (b) the PRD's declared hop order 5->6->7 is executed 5->7->6 (`cascades.py:153-157`), also unobservable. If §3.6–§3.9 prose depends on either, they are already accurate as-is.
- `demote_batches` calls `sales.write_batch_counters` on **every** batch of the project before filtering by status (`cascades.py:36-37`), so a withdrawal refreshes counters on batches it never demotes.

### OUT-OF-SCOPE OBSERVATIONS
- **§2.6, rung 2** — same defect I fixed in §3.1: it places `ERR_SEGREGATION_OF_DUTIES` on rung 2, "last on this rung", i.e. above rung-3 existence. The check cannot run without the report, so `routes/engineering.py:118` resolves the report (`ERR_ENGINEERING_ARTIFACT_NOT_FOUND`, 404) first. §2.6 should carry the same carve-out I added to §3.1. (`validation.py:67-69`.)
- **§2.8** — `rounding.half_up_cents`, `ceiling_cents`, `half_up_bp` and `truncate_bp` are dead code, and `half_up_bp` is in any case mis-implemented (it quantizes to `Decimal(1)`, i.e. whole units, with a docstring claiming basis points). No live path calls any of them, so §2.8's prose is unaffected — recording only for completeness. (`rounding.py:25-43`.)
- **§2.5/§2.7** — `store.touch` de-duplicates per request via the `_touched` set (`store.py:53,79-89`), which is what makes §3.1's "the project's `version` increments by 1 for the recalculation itself" true even though `sync()` and `recompute_posture()` both call `touch` on the same row. Pass 1's §2.5 text appears to cover this; flagging only so it is not "fixed" later.

### Pass 3 summary (verbatim)

Pass 3 is complete. All required checks pass.

## Counts

| | before pass 3 | after |
|---|---|---|
| lines | 992 | 998 |
| chars | 186,129 | 207,405 |
| diff hunks vs `PRD_FINALIZED.md` | 48 | 83 |

**58 changes: 48 ambiguity-pins, 10 mismatch-revisions.** All made with targeted `Edit` calls on unique anchors; the file was never rewritten, re-emitted or copied.

## Change list

`{section} — {kind} — {class} — {what} — {impl}`

**§2.6 (the one authorized carve-out)**
- §2.6 rung 2 — insert — mismatch — segregation-of-duties is the single identity check that cannot outrun rung 3; an unresolvable report answers `ERR_ENGINEERING_ARTIFACT_NOT_FOUND` even for the submitting engineer — `validation.py:69`

**§3.6**
- registration — insert — ambiguity — `tenancy_start_date` is a full instant, never compared to the clock; a future instant is accepted and yields negative elapsed tenancy — `services/tenants.py:31`
- registration — insert — ambiguity — `occupied_unit_id`, when supplied, must resolve to a unit of the same project — `routes/tenants.py:46`
- defaults — insert — ambiguity — `relocation_paid_cents`/`relocation_reversed_cents` 0, `notice_period_days` 0, all three instants null — `routes/tenants.py:60`
- lists — revise — **mismatch** — the per-project list filters `protected_class`; the estate-wide list does **not**, and instead filters `conversion_project_id`/`occupied_unit_id` — `routes/tenants.py:83,99`
- single-household read — insert — ambiguity — `TenantOccupant` is bound to its own record, path-compared before resolution; neither list is bound — `routes/tenants.py:116`
- pre-notice patch — insert — ambiguity — a post-notice adjustment is refused as `ERR_INVALID_STATE_TRANSITION` — `routes/tenants.py:142`
- notice service — insert — ambiguity — the endpoint reads no body, so no shape failure is reachable — `routes/tenants.py:149`
- assistance step 1 — insert — ambiguity — x3 of whole cents is exact and can never round — `services/tenants.py:51`
- assistance step 3 — insert — ambiguity — the x3/2 uplift is the only step where a half-cent can arise — `services/tenants.py:51`
- ROFR answer — revise — **mismatch** — the sponsor may also answer; the binding applies only to `TenantOccupant`, path-compared before resolution — `routes/tenants.py:185`
- ROFR answer — insert — ambiguity — the `OFFERED` state test precedes the window test, so `ERR_ROFR_WINDOW_EXPIRED` is reachable only from `OFFERED` — `routes/tenants.py:193`
- ROFR exercise — insert — ambiguity — each of the two reversal consequences is conditional on the dimension it reads — `routes/tenants.py:205`
- occupancy outcome — insert — ambiguity — `VACATE_DUE` is reachable only through the sweep, which bounds the deadline test — `routes/tenants.py:251`
- disbursement — revise — ambiguity — "any other **whole-cent** figure": a negative amount fails the shape rung first — `routes/tenants.py:228`

**§3.7**
- creation — insert — ambiguity — all three references resolve and must be in project scope, but none needs any particular state — `routes/pos.py`
- creation — insert — ambiguity — the statement's own `reserve_study_id` is metadata; readiness reads the study the **budget** names — `routes/pos.py`
- creation — insert — ambiguity — `effective_at`/`last_material_amendment_at` start null
- section write — insert — ambiguity — an omitted or empty attestation **clears** `last_attested_at`
- section write — insert — ambiguity — no precondition on the parent statement's `status`
- recount bubble — insert — ambiguity — only two directions exist; from any other status the recount rewrites the count alone
- effectiveness — insert — ambiguity — the 9-section count is the **last** test of the set
- `AMENDMENT_FILED -> EFFECTIVE` — revise — **mismatch** — identical precondition set in identical order, budget/reserve-study `ADOPTED` included, and identical side effects — `routes/pos.py`
- effectiveness — insert — ambiguity — `REGISTRATION -> PRESALE` fires only from `REGISTRATION`
- amendment filing — insert — ambiguity — `amendment_summary` is required, <=500 chars, validated then discarded
- amendment hop 2 — insert — ambiguity — affected units' `sale_status` is re-derived in the same hop — `services/cascades.py:174`
- amendment hop 3 — revise — **mismatch** — every batch's counters are refreshed first, then only failing batches demote; hop 2 moves no counter at all — `services/cascades.py:32`
- amendment hop 4 — revise — **mismatch** — fires only from `PRESALE`; the PRD's "falls all the way back to registration" claim was false — `services/cascades.py:214`
- refresh list — revise — **mismatch** — a batch threshold evaluation refreshes `presale_sold_pct` alone, not the warrantability figures — `routes/batches.py:203`

**§3.8**
- signing — revise — **mismatch** — a `WITHDRAWN` unit answers `ERR_INVALID_STATE_TRANSITION`, not a declaration error — `routes/agreements.py:49`
- signing — insert — ambiguity — `tenant_household_id` need only resolve and be in scope — `routes/agreements.py:32`
- signing — insert — ambiguity — no uniqueness rule on the unit; a second live agreement is allowed
- `sale_status` — insert — ambiguity — explicit precedence `CLOSED->SOLD`, `HARD`, `SIGNED`, else `UNSOLD`; `RESCINDED`/`VOID` contribute nothing — `services/sales.py:27`
- single-agreement read — insert — ambiguity — `Purchaser` bound to its own agreement, path-compared; lists unbound — `routes/agreements.py:115`
- patch — insert — ambiguity — the deposit ceiling is re-tested on the merged pair, after both state preconditions — `routes/agreements.py:140`
- delivery — insert — ambiguity — exactly three preconditions, no body, and re-delivery overwrites both fields without counting as a restart — `routes/agreements.py:152`
- funding — insert — ambiguity — a negative amount fails the shape rung first; a 0 deposit funds normally; funding never moves the batch's `status` — `routes/agreements.py:171`
- rescission — insert — ambiguity — reason <=500, stored only when supplied; the `FROZEN` gate precedes everything — `routes/agreements.py:224`
- warrantability read — insert — ambiguity — the two shared fields are written by whichever run executes, so the order of the read's two runs decides them — `services/sales.py:145`

**§3.9**
- creation — insert — ambiguity — `min_presale_threshold_pct` is quantized half up to 2dp on the way in, not refused — `routes/batches.py:61`
- window — insert — ambiguity — a degenerate window answers `ERR_BATCH_WINDOW_OVERLAP`, same as a sibling clash — `routes/batches.py:27`
- assignment — insert — ambiguity — no state precondition on either side; the response is the batch; `version` always +1 — `routes/batches.py:123`
- unassignment — insert — ambiguity — two `ERR_INVALID_STATE_TRANSITION` cases, wrong-batch before released-batch — `routes/batches.py:173`
- counter refresh — insert — ambiguity — the same three counters are re-derived by many other events, and no `ERR_NO_INCLUDED_UNITS` exists off the explicit evaluation — `services/sales.py:69`, `services/cascades.py:32`
- evaluation — revise — **mismatch** — admissible from three statuses with the state test first; **both** branches recompute `posture` — `routes/batches.py:193`
- threshold summary — insert — ambiguity — persists nothing (counters, `last_evaluated_at`, `version` all unchanged), ungated on units, available at every status — `routes/batches.py:247`
- release — revise — **mismatch** — full ordered precondition list; the sibling-`RELEASED` clash is `ERR_INVALID_STATE_TRANSITION`; statement precedes package; the window is not consulted; `PRESALE -> CLOSINGS` is conditional — `routes/batches.py:211`
- closing — revise — ambiguity — unassigned agreement, non-`RELEASED` batch and out-of-window clock are all the same `ERR_BATCH_NOT_RELEASED` — `routes/agreements.py:250`
- completion bubble — insert — ambiguity — a project with no `INCLUDED` unit does not complete; fires only from `CLOSINGS`; otherwise silent — `services/cascades.py:245`
- filing — insert — ambiguity — the component's **owning report** is scope-checked before shape validation; the reporting unit needs no `sale_status`; no warranty endpoint is identity-bound — `routes/warranty.py:41`
- filing — insert — ambiguity — `ERR_DECLARATION_NOT_RECORDED` also answers a recorded package with a null `warranty_start_at` — `routes/warranty.py:56`
- warranty summary — insert — ambiguity — payload shape (`claim_charges` over all claims, plus the two depth keys), may bump the project's `version`, malformed window -> `ERR_INVALID_REQUEST` after role+project only, empty string = absent, single bound or inverted -> depth 0, depth excludes the requested window, never enforced — `routes/warranty.py:242`
- triage `ADMIT` — insert — ambiguity — state->expiry->unit order; a non-`SOLD` or unresolvable unit is `ERR_INVALID_STATE_TRANSITION` — `routes/warranty.py:140`
- triage `DENY` — insert — ambiguity — strictly from `SUBMITTED` (a `REOPENED` claim cannot be denied); no expiry and no unit test — `routes/warranty.py:134`
- notes — insert — ambiguity — omitted `triage_note`/`completion_note`/`reopen_reason` never clear an earlier note — `routes/warranty.py:156,211,235`
- scheduling — insert — ambiguity — an inverted window answers `ERR_REMEDIATION_WINDOW_OVERLAP`; scheduling applies no expiry test — `routes/warranty.py:178`
- completion — insert — ambiguity — premature completion (and a null end) answer `ERR_INVALID_STATE_TRANSITION`; no expiry test — `routes/warranty.py:207`
- reopen admission — insert — ambiguity — the same `SOLD` test governs `REOPENED -> TRIAGED_ADMISSIBLE` — `routes/warranty.py:140`

## The 7 inherited items

1. **§2.6 rung-2 segregation vs existence** — fixed with the single authorized carve-out; it is the only diff outside §3.6–§3.9.
2. **§3.8 both-bases persistence / no-`version`-bump on the warrantability read** — already present from pass 2 and correct against `services/sales.py:145`; no edit made. I added only the consequence pass 2 left silent (the two shared fields being written by whichever run executes).
3. **Zero-denominator paths** — only two are live: the included-unit count (pinned as `presale_sold_pct` 0.00 and, for batch counters, `presale_pct` 0.00 on refresh) and `ratio_pct`'s own guard returning `pct2(0)`. `single_investor_max` divides by `total_unit_count`, which validation floors at 2, so it can never be zero. Both pinned in §3.9; nothing residual.
4. **Warranty summary bypassing the ladder** — resolved and pinned: a malformed instant does raise `ERR_INVALID_REQUEST` (422), but after the role check and project resolution only; an empty string is treated as absent; a single bound or `end < start` yields depth 0 in a 200; the depth excludes the requested window and is reported, never enforced.
5. **Cascade counter refresh on every batch** — pinned in §3.9 (and the mirrored mismatch fixed in §3.7 hop 3).
6. **Withdrawal-cascade details** — re-checked and I agree with pass 2: the escrow effect via `sync` is arithmetically identical to a direct write, and hops 5->7->6 are mutually independent. Unobservable; not listed as residual.
7. **Per-step rounding claims** — all verified against the `Fraction` code; two precision clarifications added to §3.6 (see verdict below).

## Rounding verdict (§3.6 / §3.8 / §3.9 vs the `Fraction` code)

Every rounding claim in my three sections is **true as written**, with two clarifications added rather than corrections:

- `relocation_assistance_cents` (`services/tenants.py:51`): the five steps are exactly as the PRD describes. Step 1's `half_up_frac(Fraction(rent*3,1))` is a vacuous rounding — the input is already whole cents — and step 3's `half_up_frac(Fraction(amount*3,2))` is the only step where a half-cent can occur. Both now stated.
- `component_cap_cents` = `half_up_frac(replacement*6000/10000)` — exactly 60 %, half up, once.
- `reopen_charge_cents` = `min(accrued + half_up_frac(accrued*2500/10000), cap)` — the uplift is rounded **before** the cap and before the `min`, and only the delta reaches the ledger, exactly as §3.9 says.
- All percentages (`presale_pct`, `presale_sold_pct`, owner-occupancy, investor concentration, `single_investor_max_pct`) build one exact `Fraction` from integer counts and round half up to 2dp exactly once; §3.8's "never from a previously rounded percentage" holds on every path.
- `pct2` quantizes `min_presale_threshold_pct` half up on input (now pinned).
- `half_up_cents`, `ceiling_cents`, `half_up_bp` and `truncate_bp` in `rounding.py` are dead code; no PRD claim rests on them.

## RESIDUAL (divergences I could not fix, they sit in another pass's section)

1. **Identity-bound endpoint enumeration.** §2.6 rung 2 (~line 300) and §3.1 (~line 613) both enumerate exactly two identity-bound endpoints (rofr-response, rescission). The implementation binds **four** — also the single-household read (`routes/tenants.py:120`) and the single-agreement read (`routes/agreements.py:119`). I pinned the two extra bindings inside §3.6 and §3.8, but those two enumerations still read as exhaustive and should gain "and reading its own record" clauses.
2. **Rung-5 universality.** §2.6 presents shape validation as covering every request parameter. The warranty summary's `window_start_at`/`window_end_at` are read straight from `request.args` (`routes/warranty.py:246`), so their refusal is not a rung-5 event. I pinned the exception locally in §3.9; the global rung-5 wording still implies no exception exists.

## Verification

- `wc -l -c`: 992 -> 998 lines, 186,129 -> 207,405 chars.
- `diff PRD_FINALIZED.md PRD_COMPLETED.md | grep -c '^[0-9]'` = **83** (was 48; grew only).
- §4 data rows: **97**. §5 rows: **50**. `### 3.` headings: **9**.
- Final line: `| `ERR_PRESALE_THRESHOLD_NOT_MET` | 409 |`.
- §1/§2/§3.1–§3.5 vs the pre-pass baseline: **exactly 1 diff hunk**, the authorized §2.6 rung-2 carve-out.
- §4 + §5 vs baseline: **byte-identical (0 diff lines)**.
- No stray files in the task directory (the baseline lives in `/tmp`).

### Orchestrator closure of Step 9's two residuals

Pass 3 correctly declined to reach into another pass's sections and reported two genuine, precisely-located divergences instead. Because Step 9's whole purpose is to leave zero residual mismatch, and because both fixes were small and fully specified by the evidence the passes had already gathered, I applied them myself rather than spawning a fourth pass:

1. **§2.6 rung 2 and §3.1 both enumerated only two identity-bound endpoints.** The implementation binds four (`validation.py:60-64`; `routes/tenants.py:116-120`, `routes/agreements.py:115-119`). Both enumerations now name all four — a right-of-first-refusal response and a `TenantOccupant`'s single-household read against the household's `id`, a rescission and a `Purchaser`'s single-agreement read against the agreement's `id` — and both now state that no collection read carries the binding, with §3.1 also recording that the comparison precedes resolution of the path identifier on all four. This makes §2.1, §2.6, §3.1, §3.6 and §3.8 mutually consistent; §2.1 was already correct from pass 1.
2. **§2.6 rung 5 read as universal over every request parameter.** Added a closing sentence carving out the one computed read that stands outside the rung: the warranty summary's `window_start_at`/`window_end_at` are interpreted by the endpoint itself (`routes/warranty.py:246`), so a malformed value is still `ERR_INVALID_REQUEST` (422) but is reported only after the role check and the project's resolution, with the degenerate cases absorbed as §3.9 sets out. Wording deliberately points at §3.9 rather than restating it, so the two cannot drift.

### Orchestrator verification of Step 9 (final artifact check)

- `PRD.md` 901 lines / 163,971 chars -> `PRD_FINALIZED.md` 905 / 167,434 -> `PRD_COMPLETED.md` **1,006 lines / 208,347 chars**.
- `cmp` confirms `PRD_COMPLETED.md` differs from BOTH `PRD_FINALIZED.md` and `PRD.md`. This was the specific failure mode I was guarding against: a byte-identical `PRD_COMPLETED.md` would have meant the scan never ran. 84 diff hunks against the finalized PRD.
- Structure intact: §4 exactly **97** data rows, §5 exactly **50** data rows, **9** `### 2.x` headings, **9** `### 3.x` headings, **5** top-level `##` headings, and the file still ends on `| ERR_PRESALE_THRESHOLD_NOT_MET | 409 |` — a real section boundary, so nothing was truncated at any point across three passes plus my two edits.
- Zero occurrences of `harder than expert`, `scaffold_difficulty_design`, `scaffold_corner_design`, `test_recipe` or `excluded_because` anywhere in the completed PRD: the difficulty instruction and both test-targeting design indices never leaked into the document the implementer reads.
- Cumulative Step 9 total: **87 ambiguity-pins and 22 mismatch-revisions** across the three passes, plus my 2 residual closures. No implementation file was touched at any point in Step 8 or Step 9 — the alignment ran in one direction only, documentation toward code.

## Pipeline complete — 2026-09-03T23:40:00.000Z

All nine steps finished. Final artifacts in this task directory: `SCAFFOLD.yaml` (97 endpoints, 14 entities, 50 errors, 9 roles), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (18 instances), `SCAFFOLD_CORNER_DESIGN.yaml` (77 recipes + 29 stubs), `test_helpers/` (9 modules), `test_suite/` (13 files, 95 tests), `workspace/implementation/` (30 files, ~4,645 lines, Flask + in-memory), `workspace/PRD.md`, `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md`, and the eight `results.{1..8}.json` sweep artifacts each reading 95/95.
