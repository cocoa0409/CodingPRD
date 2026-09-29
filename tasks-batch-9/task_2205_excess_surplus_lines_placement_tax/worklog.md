# Worklog — task_2205_excess_surplus_lines_placement_tax

## Step 1: Create task directory — 2026-08-31T23:49:08.693Z

Created `tasks/task_2205_excess_surplus_lines_placement_tax/` and `tasks/task_2205_excess_surplus_lines_placement_tax/workspace/` (directory name pre-allocated by the invoker; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T02:43:28.114Z

Ran `prd-bench-scaffold-generator` **inline in the orchestrator context** rather than in a subagent: three successive subagent attempts stalled at the 600 s stream watchdog having written zero bytes, so subagent isolation was abandoned for this step. The hard constraint was still honoured — no sibling task under `tasks/` was listed, globbed, grepped or read at any point; the scaffold was derived only from the scenario text and the generator skill's own specification.

Three files written to `tasks/task_2205_excess_surplus_lines_placement_tax/`:

- `SCAFFOLD.yaml` — §1.0–§1.7 (~3,070 lines). `domain_name: surplus-lines-placement-tax`, `api_prefix: "/"`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`; 9 rule blocks, 22 instances.
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`; 9 sections, 86 instances (58 with `test_recipe`, 28 `excluded_because` stubs).

**Complexity profile.** `primary_archetype: compliance_audit`, `secondary_archetype: ledger_reconciliation`, `complexity_layers: [dual_variant_calculation, cascading_side_effects, optimistic_concurrency, rate_threshold_triggers, version_pinning_on_approval]`, `entity_topology: flat`, `state_machine_shape: branching`, `relationship_patterns: [one_to_many, many_to_many, self_referential, polymorphic, cross_aggregate]`, `role_model: segregation_of_duties`, `consistency_model: immediate`.

**Surface counts.** 15 entities, 12 state machines, 3 concurrency rules, 7 calculations, 17 ordered validations, 56 endpoints, 53 errors, 5 roles.

The invoker asked for a task "harder than expert level", so the endpoint count (56) and error count (53) deliberately exceed §0.4's Expert bands (20–32 / 18–30). That intent is recorded in the scaffold preamble. Density was not traded for volume: all 15 entities are `parent: null` peers wired by 21 foreign keys, each with a verified reverse-reachability GET, and the interesting mechanics are concentrated in the tax/allocation ledger rather than spread across CRUD.

**Entities (15).** Broker, BrokerLicense, StateProgram, Carrier, CarrierEligibility, MarketSecurityReview, Placement, Declination, Policy, PolicyStateAllocation, Endorsement, Cancellation, TaxFilingLine, FilingBatch, Affidavit.

**Roles (5).** `PlacementBroker` is `identity: entity_backed:Broker` — its `X-User-ID` IS a `Broker.id`, which is what makes the priority-7 ownership rung and the affidavit segregation-of-duties rule expressible. `ComplianceOfficer`, `TaxFiler`, `StateRegulator`, `PlatformAdmin` are opaque.

**Difficulty rule coverage (§1.8, 22 instances).** All nine §0.5 rules are satisfied with differentiated instances:

- `dual_variant_calc` (2) — premium tax under `ALLOCATED_MULTI` vs `HOME_STATE_SINGLE` (money, on Policy) and market security score `INITIAL` vs `RECERTIFICATION` (risk scoring, on Carrier): different entity domains, as Rule 1 demands.
- `combinatorial_formula` (3) — mode (b) rounding order pinned per-allocation-row-then-summed (18019 vs 18018 on the same inputs); mode (a) the minimum-earned-premium floor overriding the type calculation; mode (c) the four-stage pinned evaluation order for endorsement adjustments.
- `non_linear_state_machine` (3) — the Placement revision cycle (`SEARCH_COMPLETE → CHANGES_REQUESTED → SEARCH_IN_PROGRESS`), the MarketSecurityReview branch fork with divergent side-effect sets per branch, and Policy's four independent parallel state dimensions on one row.
- `transitive_cascade` (2) — endorsement issue at depth 4, security decline at depth 3, from different triggers.
- `priority_pair_validation_conflict` (3) — state vs referential, business_safety vs fiscal, concurrency vs state: three distinct category pairs.
- `boundary_precision_check` (3) — a strictly-positive PPB row in the home-state waterfall, the inclusive 90-day diligent-search cutoff, and the inclusive alien trust-fund minimum: three metrics, three endpoints.
- `cross_entity_state_dependency` (2) — Policy→Carrier and FilingBatch→BrokerLicense.
- `resource_temporal_overlap` (2) — half-open policy terms (adjacency legal) vs closed eligibility windows with a 30-day cooling-off buffer: genuinely different interval semantics on different resource entities.
- `compensating_invariant` (2) — the TaxFilingLine ledger always reconciling with the Policy tax total, and allocation parts always summing to the amount being split.

**Corner coverage (§1.9, 86 instances).** Sections and counts: entities 10, state_machines 12, calculations 12, validations 9, endpoints 5, errors 26, rbac 4, cross_cutting_complexity_layers 7, consistency_model 1. Every `section:` and `claim_type:` value is drawn from the claim-extraction guide's tables. The Errors table has no `claim_type` column — it states only "verify every error code is triggerable" — so those instances use `claim_type: Error Triggerable`, and the 53-code catalog is discharged exhaustively: 19 instances with live recipes (including a nine-endpoint GET-by-id 404 sweep and a four-endpoint action-endpoint 404 sweep for MarketSecurityReview / Declination / Cancellation / Affidavit, which have no GET-by-id) plus 7 `excluded_because` stubs pointing at the §1.8 instances that already trigger the remainder.

**Adjudications made while drafting.** Recorded here because they changed the scaffold's semantics:

- `original_gross_premium_cents` was `source: system` with no input premium field anywhere — an unsatisfiable design. Changed to `source: input`.
- The Affidavit state machine declared `actor: PlacementBroker` while `POST /affidavits/{id}/sign` allowed two roles. Changed to `actor: "PlacementBroker or ComplianceOfficer"`; signing is now the matrix's only shared operation.
- `ERR_STATE_PROGRAM_NOT_FOUND` was mapped to two HTTP statuses (404 for a bad reference, 422 for a missing allocation-state program). The 422 use was renamed `ERR_ALLOCATION_STATE_PROGRAM_MISSING` in all three places.
- 4-decimal pinned `allocation_pct` values do not sum to exactly 1, so both adjustment calculations now divide each pct by the sum of pinned pcts before splitting — otherwise the return-premium and endorsement ledgers could not reconcile.
- The policy-term-overlap rule was unreachable, because a BOUND placement was barred from further issuance by a state precondition. BOUND placements now remain bindable (successive terms on one risk are legitimate), which is also what makes the `policy-create-stale-placement` OCC rule meaningful rather than dead.
- All §1.3 formulas were executed in Python and the resulting cents pinned as literals in both design files, so no `test_recipe` assert carries an unevaluated formula.

**Lint fixes.** Two systematic problems surfaced on the first `scaffold_lint.py` run (140 violations) and were fixed at the source rather than papered over:

1. 87 × check (b) — the design files named a concrete role on endpoints whose §1.5 `roles` is `[Any]` (every GET, plus the clock endpoint). Those calls now say `as: Any`.
2. 53 × check (c) — the lint treats every `input:` entry without a trailing `?` as required, and the scaffold marked nothing optional. 22 endpoint `input:` lists were corrected: all GET filter/pagination params, all PATCH fields (partial update), and every POST field whose §1.1 entity field declares a `default` (`conditions_note`, `policy_fee_cents`, `broker_fee_cents`, `min_earned_premium_pct`, `is_export_list_risk`, `stamping_fee_cap_cents`, `trust_fund_cents`, `naic_quarterly_listing`, `removed_on`, `supersedes_endorsement_id`, `rejection_reason`). This was a genuine scaffold defect: without it the §1.9 instance asserting that omitted fee fields default to zero contradicted its own endpoint declaration.

Also corrected while replaying the recipes against §1.2/§1.4/§1.6: three wrong Policy identifiers (`notice_codes_affixed`, `PENDING_NOTICES`, `UNCALCULATED`), an illegal `claim_type: Threshold Boundary` (the guide's algorithm-type rows are boundary guidance, not claim_type names), two payloads carrying fields the endpoint does not accept, and one instance that assumed invalidating a declination decrements `Placement.declination_count` — it does not, the count is pinned only at complete-search.

Final verdict block, pasted verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2205_excess_surplus_lines_placement_tax/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2205_excess_surplus_lines_placement_tax/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2205_excess_surplus_lines_placement_tax/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    56
  §1.1 entities declared:     15
  §1.8 instances scanned:     22
  §1.9 instances scanned:     58
  Calls scanned (§1.8+§1.9):  1206

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Step 3: Copy shared files — 2026-09-01T00:00:14.884Z

Copied `./INSTRUCTION.md` → `tasks/task_2205_excess_surplus_lines_placement_tax/workspace/INSTRUCTION.md` (1424 bytes). Ran ahead of Step 2's completion because it has no dependency on the scaffold; logged here in step order with its own timestamp.

## Step 4: Generate PRD — 2026-09-01T02:57:46.581Z

The PRD is written and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2205_excess_surplus_lines_placement_tax/workspace/PRD.md` — 446 lines, ends at §5 as required.

**Section inventory (26 headings)**
- §1 Introduction — 3 paragraphs framing the surplus-lines compliance chain around the two organising ideas (pinning, segregation of duties).
- §2 Global Specifications & System-Wide Principles — 12 subsections: 2.1 User and Role-Based Access Control; 2.2 API Response Structure (pasted verbatim, diff-clean against `section-2.2-response-structure.md`); 2.3 Pagination; 2.4 The Logical Clock; 2.5 Record Identity, Audit Fields and Version Semantics; 2.6 Money, Rates and Rounding Discipline; 2.7 Rate Pinning and Configuration Drift; 2.8 Cascade Propagation; 2.9 Reverse-Reachability Reads and Path Resolution; 2.10 Stale-View Rejection on Version-Guarded Writes; 2.11 The Order of Rejection (all 17 rungs, each with `applies_to` scope and error/status); 2.12 Segregation of Duties.
- §3 Business Logic & Workflows — 9 domain-grouped subsections (regulatory config; market security review + white list; placement/home-state; diligent search; binding; notices/affidavits/stamping; tax + stamping calculation; endorsements/cancellations/adjustments; filing calendar). All 33 declared transitions across the 12 state machines, and all 7 calculations, are rendered here.
- §4 Endpoint Definitions — 4-column table, all 56 endpoints.
- §5 Error Code Catalogue — 2-column table, all 53 errors.

**Hard Contract reports**
- Contract 1 (Field-Name Coverage): **PASS** — 115 distinct identifiers (104 entity field names ∪ 74 endpoint `input`/`query_params`/`path_params` identifiers) all present verbatim in backticks. Also verified: 53/53 error IDs and 5/5 role names backticked.
- Contract 2 (Rule Coverage): **PASS** — 17/17 validations with explicit priority ordering; 33/33 transitions with preconditions and side effects; 7/7 calculations with every constant; 3/3 OCC rules; all cross-entity cascades (depth-3 decline cascade, depth-4 endorsement cascade); sibling-branch symmetry maintained for APPROVE/CONDITION/DECLINE, HOME_STATE_SINGLE/ALLOCATED_MULTI, INITIAL_REVIEW/RECERTIFICATION, FLAT/PRO_RATA/SHORT_RATE, ACCEPT/REJECT, and ISSUED→VOIDED vs DRAFT→VOIDED.
- Contract 3 (§3 Path Purity): **PASS** — 765 backtick tokens scanned in §3; zero start with `/`, zero are bare HTTP methods, zero are method+path combinations. Endpoint paths appear only in §2.10/§2.11 scope lists and the §4 table, which the contract permits.

**Machine-verified against the scaffold:** §4 role column matches `roles` for all 56 endpoints exactly; §5 status column matches `http_status` for all 53 errors exactly.

**Adjudications made (scaffold internal inconsistencies)**
1. `Declination` name field: entity declares `admitted_insurer_name`, but `POST /placements/{id}/declinations` declares input `admitted_carrier_name`. Rendered both — request field is `admitted_carrier_name`, persisted/exposed field is `admitted_insurer_name`. The same endpoint's input list omits `naic_number` although the entity declares it; I described it as recorded "where one is supplied" rather than required, so a payload without it still succeeds.
2. Creation-time values for computed money/score fields: entity defaults say `null` but the creating endpoints' `side_effects` say `0`. I consistently followed the endpoint side effects (more specific to creation) for `MarketSecurityReview.score`, `Endorsement.tax_adjustment_cents`/`stamping_fee_adjustment_cents`, `Cancellation.earned_premium_cents`/`return_premium_cents`/`tax_refund_cents`/`stamping_fee_refund_cents`, `FilingBatch` totals, and `Policy.taxable_premium_cents`/`total_tax_cents`/`total_stamping_fee_cents`. Non-money pinned fields (`variant_applied`, `rating_at_review`, `capital_surplus_at_review_cents`, `reviewer_user_id`, `conditions_note`, `prepared_by_user_id`, `remitted_by_user_id`, `signed_by_user_id`, `signed_at`, `due_date`, `stamping_submitted_at`) remain `null`.
3. `PolicyStateAllocation.allocation_basis`: the field's declared enum is {`HOME_STATE_SINGLE`, `ALLOCATED_MULTI`}, but the ALLOCATED_MULTI formula body assigns the string `INSURED_VALUE_PRO_RATA`. I followed the entity enum (which also matches the calculation's own `variants[]` naming) and did not introduce the third string.
4. Listing-window semantics differ by purpose and both are stated explicitly rather than reconciled: validation rung 13 (containment of a policy `effective_date`) uses a half-open window `[listed_on, removed_on)`, while rung 14 (window-collision detection) uses closed intervals plus a 30-day cooling-off gap.
5. Ordering of the two 409s on `POST /carrier-eligibilities`: I placed `ERR_CARRIER_BELOW_STATE_CAPITAL_MINIMUM` before `ERR_ELIGIBILITY_WINDOW_CONFLICT`, matching the order in that endpoint's `side_effects`.
6. `POST /carrier-eligibilities/{id}/remove` with `removed_on` omitted: the scaffold only specifies the supplied-value and cascade cases, so I stated the omitted case defaults to the current logical clock (consistent with the cascade behaviour).
7. `stamping_fee_cap_cents` is the one configuration value the scaffold reads live at each recomputation rather than pinning onto the allocation row; I called that out explicitly in §2.7 so it isn't mistaken for an omission.

No worked examples were invented — every number in the document (rating points 40/35/30/25/15/10/0, capital tiers 5000000000/1500000000/500000000, floor 5 points, alien trust minimum 540000000, trust 15, listing 5, drift multiplier 2, bands 70/50, 90-day lookback, short-rate 0.90, late penalty rate 0.10, minimum penalty 2500 cents, 4-decimal `allocation_pct`, 6-decimal rates, 30-day cooling-off, pagination 10/1/100/0, clock epoch `2026-08-01T00:00:00Z`, due-date time `23:59:59.999Z`) comes directly from the scaffold's constants and constraints.

## Resume assessment — 2026-09-01T03:45:00.000Z

Previous run crashed during Step 5. On-disk audit:

- `SCAFFOLD.yaml` (3066 lines), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1687), `SCAFFOLD_CORNER_DESIGN.yaml` (2785) — complete, well-formed tails. **VALID, keep.**
- `workspace/INSTRUCTION.md` (1424 B) — **VALID, keep.**
- `workspace/PRD.md` (446 lines, ends on the §5 error table's last row) — **VALID, keep.**
- `test_helpers/` — all 9 declared modules present (`__init__`, `types`, `api_client`, `api_errors`, `assertions`, `factories`, `constants`, `test_users`, `fixtures`). **Appears complete; Step 5 resume will re-verify.**
- `test_suite/` — only `conftest.py` + `test_01_regulatory_configuration.py` (8 `Design:` tags). The two design indices hold 22 + 58 = 80 non-stub instances, so the suite is **INCOMPLETE → Step 5 resumes here.**
- `workspace/implementation/` — 56 routes registered across 12 blueprints + 7 calc modules + `start.sh`; smoke-booted successfully on a scratch port. **VALID, keep.**
- `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md` — absent. Steps 8/9 pending.

Resuming at Step 5 (complete the test suite), then Steps 7 → 8 → 9.

## Step 5: Generate unit tests (resumed) — 2026-09-01T04:52:00.000Z

The suite is finished and verified.

### Modules and test counts (102 tests total)

| Module (in `test_suite/`) | Tests | Focus |
|---|---|---|
| `test_01_regulatory_configuration.py` | 8 | brokers, licences, state programs (pre-existing, verified) |
| `test_02_carrier_security_and_white_list.py` | 16 | security scoring, review branches, decline cascade, eligibility windows |
| `test_03_placements_and_diligent_search.py` | 16 | home-state derivation, diligent search, declinations, revision cycle |
| `test_04_policy_issuance.py` | 12 | ladder priority pairs, carrier/licence dependencies, term adjacency |
| `test_05_tax_calculation.py` | 10 | both allocation variants, per-row rounding, stamping cap, rate pinning |
| `test_06_notices_affidavits_stamping.py` | 9 | notice affixing, affidavits, stamping accept/reject, 4 policy dimensions |
| `test_07_endorsements.py` | 11 | pinned 5-step recomputation, 4-hop cascade, void reversibility, ledger invariant |
| `test_08_cancellations.py` | 8 | refund arithmetic, min-earned floor, largest-remainder invariants |
| `test_09_filing_calendar.py` | 9 | batch birth, due date/penalty floor, sweep, submission + remittance rungs |
| `test_10_access_control.py` | 3 | rungs 1-3 (auth, role, ownership) |

### Ledger — all 80 non-stub instances discharged, 0 skipped

Verified mechanically by parsing the two design YAMLs and every test docstring:
- Queue A (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`): 22 non-stub instances, **22 covered**, each by **>=2 tests** (the skill's minimum) — no instance under-covered.
- Queue B (`SCAFFOLD_CORNER_DESIGN.yaml`): 58 instances carrying a `test_recipe`, **58 covered**; the 28 recipe-less (stub) instances were correctly left alone — no test tags a stub.
- No instance was skipped under the PRD-first filter; every recipe survived, though several were translated in the ladder-consistent / PRD-verbatim reading rather than the yaml's shorthand (documented below).

### Verification sweeps (all clean)

- `py_compile` on all 19 files: OK. `pytest --collect-only`: **102 tests collected, 0 errors**. `pytest --setup-plan`: every fixture resolves, no "fixture not found".
- Every `test_helpers` import name resolves at runtime (checked against `dir(test_helpers)`): 0 missing.
- `Design:` tags: exactly one per test, always the final docstring line, all 102 resolve to a real instance; no dual tags, no untagged tests.
- PRD citations: **103 quotes, all 103 verbatim-greppable** against `workspace/PRD.md` after whitespace normalisation.
- No `skip`/`xfail` markers; no occurrence of "scaffold" in emitted code; `pyflakes` reports zero unused imports in the ten test modules (the only hits are the deliberate fixture re-exports in `conftest.py`, which carry `noqa`).

### `test_helpers` extensions made

`test_helpers/` (9 modules) was inherited from the crashed run and required **no changes this session**. Extensions made earlier to support modules 06-10, all additive so existing names kept working: `World.request_changes`, `.invalidate_declination`, `.stamping_decision`, `.remit_batch`, `.sign_affidavit`, the `self.affidavit` slot, and five composite fixtures — `affixed_world`, `stamping_submitted_world`, `affidavit_world`, `ca_home_world`, `nv_home_world` — re-exported through `conftest.py`.

### Deliberate deviations from the design indices (yaml bugs / ambiguities)

- `coverage_class: "CASUALTY"` -> `EXCESS_CASUALTY`; `line_type=RETURN_PREMIUM` -> `CANCELLATION_RETURN`; `allocation_basis=INSURED_VALUE_PRO_RATA` -> `ALLOCATED_MULTI` (the yaml values are not in the PRD enums).
- Cancellation-date-out-of-term and flat-after-inception are asserted at **process** (rung 17), with create returning 201 — the ladder-consistent reading.
- `ERR_REVIEW_ALREADY_OPEN` asserted on **start**, not create; `diligent_search_completed_at` never asserted (not PRD-declared); post-endorsement NV stamping fee asserted only through reading-independent values, since the PRD's literal rule and the design's pinned number disagree; the eligibility exact-30-day boundary was expressed without the non-derivable arithmetic.

## Step 6: Generate implementation — (completed by the crashed run; verified on resume) — 2026-09-01T04:52:00.000Z

No regeneration needed. Audit on resume: `workspace/implementation/` holds `app.py` (12 blueprints registered, in-memory store, nothing seeded, logical clock epoch 2026-08-01T00:00:00Z), `start.sh` (foreground, reads `$PORT`, binds 0.0.0.0, conditional pip install), `requirements.txt`, 11 top-level modules (`auth`, `clock`, `eligibility`, `envelope`, `errors`, `ledger`, `licensing`, `moneyutil`, `serialize`, `store`, `validation`), `calc/` (7 formula modules) and `routes/` (13 modules). Route count across `routes/` is **56**, matching §1.5 exactly. Smoke-booted on a scratch port and served a request; no boot errors.

## Step 7: Run tests and iterate — 2026-09-01T05:02:00.000Z

All 8 parallel rounds pass 102/102.

**Iterations run:** 2 (each an 8-round parallel stability sweep, 102 tests per round). Sweep 1: 94/102 in all 8 rounds, 8 deterministic failures (identical across every round — no flakiness observed). Sweep 2 after fixes: 102/102 in all 8 rounds.

**Tests deleted:** none. Every failing assertion traced to a verbatim PRD sentence and was uniquely derivable; no PRD-silence or collapse pattern applied.

**Fixes applied to `test_suite/`** (2 test bugs, both assertion mis-translations of PRD; STEP 2):
- `test_suite/test_05_tax_calculation.py` — `test_one_request_returns_every_row_it_touched_already_updated` asserted `period_key == "2026-08"` for all three allocation lines, but PRD 3.7 says a line's `period_key` is "formatted according to that state's `filing_frequency` — `YYYY-MM` for `MONTHLY` and `YYYY-Qn` for `QUARTERLY`", and the California program in `test_helpers/factories.py` is `QUARTERLY`. Assertion now expects `2026-08` for TX/NV and `2026-Q3` for CA. Made stricter/more faithful, not weaker.
- `test_suite/test_09_filing_calendar.py` — `test_voiding_an_endorsement_whose_tax_was_already_remitted_is_refused` expected HTTP 422 for `ERR_ENDORSEMENT_ALREADY_REMITTED`; PRD §5's error catalogue lists that error at **409**, and PRD §2.11 rung 9 lists it among the state-legality errors. Status corrected to 409; the exact `error_id` assertion was preserved.

**Fixes applied to `test_helpers/`:** none needed — all fixtures/factories/role headers were PRD-consistent.

**Fixes applied to `implementation/`:**
- `routes/eligibilities.py` (`remove_eligibility`), `routes/carriers.py` (`_decline_cascade`), `routes/policy_tax.py` (`submit_stamping`), `routes/affidavits.py` (`sign_affidavit`) — clock-stamped instants (`removed_on`, `stamping_submitted_at`, `signed_at`) were re-serialised via `clock.now_iso()` (adding `.000`); switched to `clock.now_raw()` so they carry the clock's own value. PRD 2.5 mandates three fractional digits only for `created_at`/`updated_at`; PRD 2.4 says these fields are "read from the clock", and the clock capability "echoes the `current_utc` now in force". 4 of the 8 failures.
- `validation.py` (`req_state_exposures`) — an **empty** `state_exposures` array was rejected at rung 6 as `ERR_INVALID_REQUEST`. PRD 3.3 states verbatim: "First, an empty `state_exposures` array is refused outright with `ERR_HOME_STATE_INDETERMINATE`." Empty is now allowed at shape level and falls through to the home-state waterfall (which already raised the 422). A *missing* array still reports 400, matching `test_placement_create_missing_state_exposures_returns_invalid_request`.
- `validation.py` (`opt_str`, new `allow_blank` parameter), `routes/policy_tax.py` (`stamping_decision`), `routes/carriers.py` (`decide_review`) — a blank-string `rejection_reason` / `conditions_note` tripped the rung-6 non-empty check and reported `ERR_INVALID_REQUEST`. Both fields are declared *optional* in PRD 3.6/3.2, and their non-emptiness is a rung-16 documentary check owned by the REJECT / CONDITION branch (`ERR_REJECTION_REASON_REQUIRED`, `ERR_CONDITIONS_NOTE_REQUIRED`, both 422). Blank now falls through to the branch-specific 422.

No implementation check required by PRD was removed or weakened, no endpoint/field/capability was added, no `skip`/`xfail` was introduced, and storage remains in-memory dicts with nothing seeded at boot.

Verified by the orchestrator: `results.1.json` … `results.8.json` all report `passed == total == 102`.

## Step 8: Finalize PRD — 2026-09-01T05:07:00.000Z

Done. `PRD_FINALIZED.md` written at `workspace/PRD_FINALIZED.md`.

### Line counts
- `PRD.md`: 446 lines — `PRD_FINALIZED.md`: 446 lines — **0.0% line delta** (5 in-place sentence revisions, no new lines/sections; +2,050 chars ≈ +2.5% by bytes).

### Changes

- **§2.4 (Logical Clock)** — *insert* — pinned the serialisation of clock-read instant fields: `signed_at`, `stamping_submitted_at`, and a clock-defaulted `removed_on` (direct or cascaded) carry the clock's value **verbatim** — the same string the clock capability echoes as `current_utc` — rather than being re-serialised to the three-fractional-digit form §2.5 mandates for `created_at`/`updated_at`; boot value stated as `2026-08-01T00:00:00.000Z` — `implementation/clock.py:66` (`now_raw`), `routes/affidavits.py:88`, `routes/policy_tax.py:77`, `routes/eligibilities.py:87`, `routes/carriers.py:149`.
- **§3.3 (Opening a Placement)** — *revise* — replaced "That array must be non-empty" (which contradicted the waterfall's own step 1 and would force a 400) with: `state_exposures` must be *supplied* (missing/null => `ERR_INVALID_REQUEST`), while a **present-but-empty** array passes field-shape and is refused by the waterfall's first step (`ERR_HOME_STATE_INDETERMINATE`, 422) — `implementation/validation.py:233-240`, `implementation/calc/home_state.py:18-20`.
- **§3.2 (The decision)** — *insert* — `conditions_note` carries no rung-6 non-emptiness check; empty/whitespace-only passes shape and is treated as absent by the `CONDITION` branch (=> `ERR_CONDITIONS_NOTE_REQUIRED`, 422) — `implementation/routes/carriers.py:165,182`, `validation.py:69` (`allow_blank`).
- **§3.6 (The stamping decision)** — *insert* — same pinning for `rejection_reason`: blank passes shape, `REJECT` branch reports `ERR_REJECTION_REASON_REQUIRED` (422) — `implementation/routes/policy_tax.py:92,101`.
- **§2.11 rung 17** — *revise* — resolved the PRD's internal contradiction: `ERR_ENDORSEMENT_ALREADY_REMITTED` moved out of the "(all 422)" group and marked **409**, consistent with rung 9 and §5 — `implementation/errors.py:38`, `routes/endorsements.py:211`.

### Per-edit pre-edit search log

**Edit 1 — §2.4 clock instant serialisation**
- (a) Subject: format of every persisted timestamp field, and specifically clock-derived ones.
- (b) Enumerated: `grep -rn "now_raw|now_iso|clock.now()|clock.fmt"` across `implementation/` -> `clock.py:22,62,66,70`; `routes/clock_routes.py:19` (echo); `routes/policy_tax.py:77`; `routes/affidavits.py:88`; `routes/eligibilities.py:75-91`; `routes/carriers.py:149-150`; `store.py:45,68` (`created_at`/`updated_at` -> `now_iso`, 3 digits); `routes/filing.py:116,122` (`due_date` -> `clock.fmt`, `23:59:59.999Z`); `calc/filing.py:20` (`period_key`); `serialize.py:18` (licence status). Also read every `req_datetime`/`opt_datetime` callsite (`brokers.py:55`, `policies.py:46-47`, `endorsements.py:47`, `cancellations.py:28`, `placements.py:143`, `eligibilities.py:28,75`) — all client-supplied instants are stored as the *raw supplied string*.
- (c) Adjustment: restricted the claim to an explicit three-field list plus "defaulted from the clock", and explicitly carved out `created_at`/`updated_at`. Deliberately said nothing about client-supplied instants (`listed_on`, `effective_date`, `declined_on`, `expires_on`, a *supplied* `removed_on`) and nothing about `due_date`/`period_key`, so the sentence cannot be read as forcing or forbidding a format on those paths.

**Edit 2 — §3.3 `state_exposures` emptiness**
- (a) Subject: shape validation and downstream consumption of `state_exposures`.
- (b) Enumerated: `validation.py:233-263` (`req_state_exposures`, `req_array(allow_empty=True)`), `routes/placements.py:31,34,42`, `calc/home_state.py:9-37`, and the only other consumer `calc/premium_tax.py` via §3.7 `ALLOCATED_MULTI`; grepped `req_array`/`req_code_array` callsites (`state_programs.py:44,103`, `policies.py:154`) to confirm no cross-contamination with other array fields.
- (c) Adjustment: scoped the sentence to `state_exposures` alone and split "missing/null => 400" from "present-but-empty => waterfall", matching `present()`-based `_MISSING`/`None` handling; left the per-entry rules verbatim.

**Edit 3 — §3.2 `conditions_note`**
- (a) Subject: rung-6 blank-string policy for optional strings.
- (b) Enumerated: `grep -rn "opt_str|req_str"` over `routes/` -> only `carriers.py:165` and `policy_tax.py:92` pass `allow_blank=True`; `placements.py:144` (`naic_number`) and every `req_str` (`firm_name`, `license_number`, `legal_name`, `naic_number`, `insured_name`, `admitted_carrier_name`, `policy_number`, `period_key`, FK id strings) still reject blank at rung 6. Read `validation.py:56-72` and `carriers.py:174-193` for check ordering (score-band check precedes the note check; note stored only on the `CONDITION` branch).
- (c) Adjustment: named the field explicitly instead of generalising to "optional strings" — a general claim would have wrongly licensed blank `naic_number`. Said "treated as absent by the `CONDITION` branch" rather than restating the whole branch, so the existing verbatim `ERR_CONDITIONS_NOTE_REQUIRED` sentence and the score-band precedence are untouched.

**Edit 4 — §3.6 `rejection_reason`**
- (a) Subject: same as Edit 3, for the stamping decision.
- (b) Enumerated: `routes/policy_tax.py:83-110` (whole handler: rung-9 `stamping_status != SUBMITTED` precedes the reason check; `rejection_reason` is never persisted on the policy; `ACCEPT` ignores it entirely), plus `validation.py:69-72`. Cross-checked the ladder in §2.11 (rung 9 < rung 16) against impl ordering.
- (c) Adjustment: confined the claim to shape validation ("still passes the field-shape rung") so it does not imply the reason check outranks the `SUBMITTED` state check, and avoided asserting anything about `ACCEPT`-branch storage.

**Edit 5 — §2.11 rung 17 status for `ERR_ENDORSEMENT_ALREADY_REMITTED`**
- (a) Subject: the HTTP status and ladder position of `ERR_ENDORSEMENT_ALREADY_REMITTED`.
- (b) Enumerated: `grep -rn "ENDORSEMENT_ALREADY_REMITTED"` -> `errors.py:38` (409, in the state block) and the single raise site `routes/endorsements.py:209-212` (inside `void_endorsement`, after the DRAFT/ISSUED state check, before any recomputation); also re-read §2.11 rung 9, §3.8 void paragraph, and §5 catalogue.
- (c) Adjustment: kept "voiding an endorsement" in rung 17's applies-to list and left rung 9's mention untouched, correcting only the status grouping — the narrower alternative (deleting the error from rung 17) would have made the rung-17 applies-to list self-inconsistent and dropped the only documented rung reference for the void path.

## Step 9: Complete PRD — 2026-09-01T05:28:00.000Z

`PRD_COMPLETED.md` is written and the sweep is complete.

### (a) File stats

| | lines | chars |
|---|---|---|
| `workspace/PRD_FINALIZED.md` (source) | 446 | 83,102 |
| `workspace/PRD_COMPLETED.md` | 446 | 99,940 |

Char delta **+16,838**. Line count unchanged — every change is an in-paragraph insert or revision; no new paragraphs, no new sections, no new endpoint-table or error-catalogue rows.

### (b) Counts

54 changed lines: **51 ambiguity-pins**, **3 mismatch-revisions**.

Independently verified as already exact and left untouched: the §4 endpoint table (56 rows, exact set match against the 56 `@bp.*` routes) and the §5 error catalogue (53 codes, exact code+status match against `errors.py:ERROR_STATUS`).

### (c) Change list

- §2.1 — insert — ambiguity — blank-header test trims whitespace; surviving `X-User-ID` stored untrimmed — `implementation/auth.py:26`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from uppercase ASCII + digits — `implementation/envelope.py:19`
- §2.2 — insert — ambiguity — `api_request_timestamp` reads the host wall clock, not the logical clock — `implementation/envelope.py:23`
- §2.3 — insert — ambiguity — non-integer / out-of-range `limit`/`offset` -> `ERR_INVALID_REQUEST`; empty-string param = absent; undeclared params ignored — `implementation/envelope.py:78`
- §2.3 — revise — ambiguity — `created_at` ties broken by insertion sequence — `implementation/store.py:72`
- §2.4 — revise — ambiguity — `current_utc` echoed byte-for-byte; required, unparseable -> `ERR_INVALID_REQUEST` — `implementation/clock.py:70`
- §2.4 — insert — ambiguity — all eight client instants stored verbatim; time-of-day mandatory, date-only rejected — `implementation/clock.py:15`
- §2.5 — revise — ambiguity — `created_at` from the logical clock — `implementation/store.py:42`
- §2.5 — insert — ambiguity — `updated_at` from the logical clock and equal to `created_at` until first mutation — `implementation/store.py:42`
- §2.5 — insert — ambiguity — `version` is 1 at first persist — `implementation/store.py:42`
- §2.7 — revise — ambiguity — PATCH treats `null` as absent, except `stamping_fee_cap_cents` where `null` clears the cap; empty body still bumps `version`; non-listed fields ignored — `implementation/routes/state_programs.py:89`
- §2.8 — revise — ambiguity — only rows whose money figures actually change get `version`/`updated_at` bumped — `implementation/calc/endorsement_adj.py:37`
- §2.9 — insert — ambiguity — unserved path -> `ERR_NOT_FOUND`; bad method -> `ERR_METHOD_NOT_ALLOWED`; both still behind rungs 1-2 — `implementation/app.py:60`
- §2.10 — insert — ambiguity — missing/non-integer `expected_*_version` is a rung-6 `ERR_INVALID_REQUEST`, not a 412 — `implementation/auth.py:91`
- §2.11 rung 6 — insert — ambiguity — duplicate `policy_number`, contradictory `premium_delta_cents` sign, out-of-term endorsement `effective_date` all report `ERR_INVALID_REQUEST` — `implementation/routes/policies.py:56`
- §2.11 rung 9 — insert — ambiguity — subject's own status tested before every other rung-9 condition, with the two `ERR_PLACEMENT_ALREADY_BOUND` exceptions — `implementation/routes/placements.py:117`
- §2.11 rung 14 — insert — ambiguity — collision looks only at existing `removed_on`; null collides always; strictly-more-than-30-days required; new `listed_on` never compared to existing `listed_on` — `implementation/eligibility.py:20`
- §3.1 — insert — ambiguity — suspend has no state precondition and no body, still bumps `version` — `implementation/routes/brokers.py:39`
- §3.1 — insert — ambiguity — licence fields all required, shape-checked in stated order; no uniqueness on licences — `implementation/routes/brokers.py:48`
- §3.1 — revise — ambiguity — state-program payload: all fields required bar the cap; exact shape-check order; duplicate `state_code` raised only after full shape clearance — `implementation/routes/state_programs.py:20`
- §3.2 — revise — ambiguity — carrier payload shape order; `naic_number` conflict raised only after shape clearance — `implementation/routes/carriers.py:24`
- §3.2 — revise — ambiguity — carrier PATCH treats `null` as absent; empty body still bumps `version` — `implementation/routes/carriers.py:60`
- §3.2 — revise — ambiguity — `start_review` order: review `DRAFT` (`ERR_INVALID_STATE`) -> `ERR_REVIEW_ALREADY_OPEN` -> capital-on-record (`ERR_INVALID_STATE`) — `implementation/routes/carriers.py:113`
- §3.2 — insert — ambiguity — review `created_at` tie resolved in favour of the later-persisted review — `implementation/store.py:72`
- §3.2 — revise — ambiguity — decide-review shape order; note stored only on `CONDITION`, discarded otherwise — `implementation/routes/carriers.py:155`
- §3.2 — insert — ambiguity — eligibility removal: `removed_on` ordering check precedes the `WHITE_LISTED` state test; `null` = omitted; non-`WHITE_LISTED` -> `ERR_INVALID_STATE`; no version guard — `implementation/routes/eligibilities.py:70`
- §3.3 — revise — ambiguity — `broker_id` taken verbatim from `X-User-ID`, never resolved as a Broker; exposure entries normalised to exactly two keys, extras discarded — `implementation/routes/placements.py:24`, `implementation/validation.py:233`
- §3.4 — insert — ambiguity — `begin_search` tests status before suspension; unresolvable `broker_id` is not suspended; `ERR_PLACEMENT_ALREADY_BOUND` counts `CANCELLED` policies and precedes the `SEARCH_COMPLETE` test — `implementation/routes/placements.py:72,117`
- §3.4 — insert — ambiguity — declination shape order with optional `naic_number` last; `BOUND` refusal precedes the `RECORDED` status test — `implementation/routes/placements.py:136,170`
- §3.4 — revise — ambiguity — missing home-state program on `complete_search` -> `ERR_STATE_PROGRAM_NOT_FOUND` (404), after status and before sufficiency — `implementation/routes/placements.py:89`
- §3.5 — revise — ambiguity — duplicate `policy_number` -> `ERR_INVALID_REQUEST` (400), last shape check, not a 409 — `implementation/routes/policies.py:56`
- §3.5 — insert — ambiguity — home-state program existence checked at issuance -> `ERR_STATE_PROGRAM_NOT_FOUND` (404) — `implementation/routes/policies.py:67`
- §3.6 — revise — ambiguity — `notice_codes` must be an array of non-empty strings, may be empty; `PENDING_NOTICES` refusal precedes content checks; comparison case-sensitive; unconfigured home state => empty required set — `implementation/routes/policies.py:150`
- §3.6 — revise — ambiguity — affidavit signing is four ordered checks; `ComplianceOfficer` exempt from the ownership comparison; own `status` must be `DRAFT` — `implementation/routes/affidavits.py:62`
- §3.6 — revise — ambiguity — `submit_stamping` tests `stamping_status == PENDING` first, ahead of notices and tax — `implementation/routes/policy_tax.py:62`
- §3.6 — revise — ambiguity — `REJECT` moves compliance to `DEFICIENT` only from `NOTICES_AFFIXED`/`COMPLIANT`, else leaves it; `SUBMITTED` test precedes the `rejection_reason` check — `implementation/routes/policy_tax.py:84`
- §3.7 — revise — ambiguity — `calculate_tax` is three ordered checks (`ISSUED` -> `UNCALCULATED` -> programs), home state tested first then allocated states ascending — `implementation/routes/policy_tax.py:21`, `implementation/calc/premium_tax.py:85`
- §3.7 — **revise — mismatch** — allocation listing ordered by `state_code`, rows carry no state-program FK, and line `VOIDED` is never written by any operation (PRD claimed supersession writes it) — `implementation/store.py` (`allocations_of`), `implementation/routes/endorsements.py:120`
- §3.8 — revise — ambiguity — endorsement `effective_date` containment inclusive at both ends; body shape order; `sequence_number` counts `VOIDED` endorsements — `implementation/routes/endorsements.py:35`
- §3.8 — revise — ambiguity — issuance is five ordered checks led by the endorsement's own `DRAFT` status; "resulting" gross = issued set plus this delta minus the superseded target's — `implementation/routes/endorsements.py:139`
- §3.8 — insert — ambiguity — supersede unwind negates the target's *recorded* per-state movements and precedes the new before-snapshot; target keeps its adjustment figures; `tax_status` move unconditional except from `REMITTED` — `implementation/routes/endorsements.py:166`
- §3.8 — insert — ambiguity — void tests own `DRAFT`/`ISSUED` first (`ERR_INVALID_STATE`), ignores policy status; compensating line negates premium too and skips all-zero states; voided record keeps its adjustment figures — `implementation/routes/endorsements.py:190`
- §3.8 — **revise — mismatch** — cancellation *request* applies no policy-term test to `cancellation_date` and no policy status/tax test; the term test is deferred to processing — `implementation/routes/cancellations.py:21`
- §3.8 — revise — ambiguity — processing is three ordered checks led by `REQUESTED`; `tax_status` move follows the endorsement rule — `implementation/routes/cancellations.py:54`
- §3.8 — insert — ambiguity — whole-day count = `seconds // 86400` floored; out-of-term test precedes the type branch; zero-or-negative term => whole taxable premium unearned for `PRO_RATA` and `SHORT_RATE` — `implementation/calc/return_premium.py:16`
- §3.8 — insert — ambiguity — refundability flags read live from current program config (not pinned); rates stay pinned; unconfigured state refunds nothing — `implementation/calc/return_premium.py:68`
- §3.8 — revise — ambiguity — a `CANCELLATION_RETURN` line is emitted for *every* allocation row, including all-zero ones — `implementation/routes/cancellations.py:83`
- §3.8 — **revise — mismatch** — processing a cancellation does **not** recompute allocation rows or the policy's `gross`/`taxable`/`total_tax`/`total_stamping_fee`; it only reads them (PRD said rows are recomputed in place) — `implementation/routes/cancellations.py:74`
- §3.9 — insert — ambiguity — `period_key` at create is any non-empty string; no uniqueness on the state/broker/period triple — `implementation/routes/filing.py:47`
- §3.9 — revise — ambiguity — prepare: `OPEN` status test precedes `ERR_PERIOD_KEY_MALFORMED` — `implementation/routes/filing.py:94`
- §3.9 — insert — ambiguity — 2,500-cent floor applies to a late batch even with zero swept lines — `implementation/calc/filing.py:75`
- §3.9 — revise — ambiguity — submit: `PREPARED` status test precedes `ERR_BATCH_EMPTY` — `implementation/routes/filing.py:132`
- §3.9 — revise — ambiguity — remit: amount shape first, then `SUBMITTED`, then segregation, then amount mismatch — `implementation/routes/filing.py:162`
- §4 — insert — ambiguity — multi-record writes return only the record the endpoint is named for (review not carrier, endorsement not policy, batch not lines, policy not placement) — every route's `return ok(serialize.public(rec))`

## Pipeline complete — 2026-09-01T05:28:00.000Z

All nine steps have valid artifacts on disk. Final state: 15 entities, 56 endpoints, 53 errors, 102 tests, 8/8 stability-sweep rounds green at 102/102.
