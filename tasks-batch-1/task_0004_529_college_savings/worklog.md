# Worklog — task_0004_529_college_savings

## Step 1: Task directory — 2026-05-27T00:26:00Z

Pre-assigned task directory `tasks/task_0004_529_college_savings/workspace/` already created by orchestrator (skipped index-scan).

## Step 2: Generate scaffold — 2026-05-27T00:45:00Z

Clean lint verdict.

---

## Summary

Generated three files under `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0004_529_college_savings/`:

- `SCAFFOLD.yaml`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `SCAFFOLD_CORNER_DESIGN.yaml`

**Complexity profile**: Expert tier — primary archetype `compliance_audit` + secondary `ledger_reconciliation`; layers: dual-variant calculation, cascading side effects, rate-threshold triggers, derived-field reconciliation, optimistic concurrency. Topology `flat`, state machines `branching`, role model `segregation_of_duties`, consistency `immediate`.

**Counts**:
- Entities: 10 (`Donor`, `Beneficiary`, `Account`, `ScheduledContribution`, `Contribution`, `Withdrawal`, `BeneficiaryChange`, `StateTaxIncentive`, `Form1099Q`, `ClockState`)
- State machines: 6 (`Account` posture, `ScheduledContribution` linear+cancel, `Contribution` post+reverse, `Withdrawal` branching-with-revert, `BeneficiaryChange` branching, `Form1099Q` cyclic ISSUED↔CORRECTED↔REISSUED)
- Concurrency rules: 2 (both OCC on `Account.version`)
- Calculations: 4 (`earnings_ratio` dual-variant, `excess_withdrawal_penalty` threshold-with-nested-rounding, `k12_excess_calc` threshold, `state_tax_incentive_match` tiered CA/NY)
- Validations: 18 (priority 1–18, categories auth → existence → state → safety → referential → fiscal → request-shape)
- Endpoints: 51 (incl. 3 test-driving: `/_clock/set_current_utc`, `/_clock` GET, `/_scheduler/tick`, `/_market/credit_earnings` — the market-earnings endpoint was added because no business endpoint can produce unrealized appreciation, which is required to test the `earnings_ratio` dual variant)
- Errors: 18 (every error triggerable from at least one §1.8/§1.9 instance)
- Roles: 4 (`AccountOwner` entity_backed:Donor; `CustodianAgent`, `ComplianceOfficer`, `SystemTaxAuthority` all opaque)

**§1.8 coverage** (Difficulty Design — 18 instances, exactly 2 per rule):
- `dual_variant_calc`: earnings_ratio pre-vs-post (Withdrawal) + state_tax_incentive CA cap vs NY tiered (Donor)
- `combinatorial_formula`: excess_withdrawal_penalty (mode a, ≥3 inputs + branch) + NY tiered match (mode b, per-tier rounding order)
- `non_linear_state_machine`: Withdrawal branching+revert (REJECTED→DRAFT cycle) + BeneficiaryChange branching (PENDING→{APPROVED,REJECTED})
- `transitive_cascade`: Contribution.POST → Account ledger → StateTaxIncentive (depth 3) + Withdrawal.DISBURSE → Account.ytd_k12 → Form1099Q (depth 3, different trigger)
- `priority_pair_validation_conflict`: state (6) beats fiscal (15) on approve-from-DRAFT-with-insufficient-balance + auth (3) beats state (7) on segregation-of-duties-plus-stale-version
- `boundary_precision_check`: K-12 cap exact equality (numeric, Withdrawal.approve) + Form1099Q issue Dec-31 vs Jan-1 (temporal, Form1099Q.issue)
- `cross_entity_state_dependency`: Withdrawal × BeneficiaryChange (submit blocked by pending change) + Withdrawal × Account (submit blocked by RESTRICTED)
- `resource_temporal_overlap`: K-12 annual cap aggregate-capacity on Account + Contribution reverse 72h strict-adjacency on Contribution
- `compensating_invariant`: Contribution POST+REVERSE preserves `account_balance_cents` (numeric ledger) + BeneficiaryChange round-trip preserves `beneficiary_id` (categorical FK)

**§1.9 coverage** (Corner Design — 33 instances across all 9 taxonomy sections from claim-extraction-guide.md): entities (10 — creation, retrieval, listing, not_found, required_fields, computed_fields, system_fields, type_constraints, parent_relationships, immutability), state_machines (8 incl. 3 `excluded_because:` stubs), calculations (4 incl. 1 stub), validations (6 — uniqueness, family-member, correction window, revision limit, insufficient balance), endpoints (1 — scheduler tick), errors (1 audit stub), rbac (3 — missing-header, exclusive-op-denial, segregation), cross-cutting layers (4 incl. 3 stubs), consistency model (1 — immediate visibility).

**Lint**: `python3 skills/prd-bench-scaffold-generator/scaffold_lint.py tasks/task_0004_529_college_savings/` → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (392 calls scanned, 51 endpoints, 10 entities).

## Step 3: Copy INSTRUCTION.md — 2026-05-27T00:46:00Z

Copied `INSTRUCTION.md` from project root to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-05-27T00:55:00Z

All contracts pass.

## Summary

**Generated:** `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0004_529_college_savings/workspace/PRD.md` — 293 lines.

**Sections covered:**
- §1 Introduction (2 paragraphs covering domain goals + calculations/temporal cross-cutting concerns)
- §2 Global Specifications (9 subsections): 2.1 RBAC + identity translation for all 4 roles, 2.2 fixed verbatim envelope, 2.3 Pagination, 2.4 Common Resource Shape & Versioning (with `ClockState` exception), 2.5 Path Traversal of Nested Resources, 2.6 Money/Rounding/Cents Arithmetic, 2.7 OCC on Account (both `concurrency_rules` entries named explicitly with `expected_account_version`, `ERR_STALE_ACCOUNT_VERSION`, HTTP 412), 2.8 Validation Priority (11-tier ordered list mapping each `validations[].priority` to its `error_id`), 2.9 Hierarchical Consistency
- §3 Business Logic (10 subsections following a hybrid lifecycle/role grouping): donors-beneficiaries-accounts setup, account posture (OPEN/RESTRICTED/CLOSED), scheduled contributions, contributions posting/reversing, withdrawals lifecycle, basis/earnings/K-12/penalty calculations, beneficiary changes, state tax incentives, Form 1099-Q lifecycle, test-driving capabilities
- §4 Endpoint table (4 columns: Method/Path/Description/Authorized Role(s)) — all 51 endpoints
- §5 Error catalog (2 columns: Error ID/HTTP Status Code) — all 18 errors

**Scattering decisions:**
- Endpoint inputs spread across subsections — e.g., withdrawal-approve's `expected_account_version` lives in both §2.7 OCC and §3.5 approve narrative; segregation-of-duties guard for that same approve sits in §2.1; balance precondition lives in §3.5; basis/earnings pinning lives in §3.6.
- `K12_ANNUAL_CAP_CENTS: 1000000` embedded as "$10,000 (1,000,000 cents)"; CA/NY cap and rate constants embedded in business prose with both dollar and cent forms.
- Foreign keys never declared as schema — only implied through actions (e.g., "payload referencing the `donor_id` and the `beneficiary_id`").
- §3 uses state-transition framing and role+action verbs throughout — zero URL paths and zero bare HTTP method tokens in §3 backticks.

**Contract reports:** Field coverage PASS (44/44 fields, 3/3 inputs, all query params). Rule coverage PASS (18/18 validations, 2/2 OCC, 20/20 transitions, 4/4 calculations, 18/18 errors, all side_effects, all enum/default reconstructible, sibling-branch symmetry intact). Path purity PASS (471 backtick tokens in §3; 0 starting with `/`, 0 bare HTTP-method tokens).

## Step 5: Generate unit tests — 2026-05-27T01:10:00Z

### File counts
- **test_helpers/** — 9 files: `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`
- **test_suite/** — 9 files: `conftest.py`, `test_01_entities_crud.py`, `test_02_state_machines.py`, `test_03_calculations.py`, `test_04_validations.py`, `test_05_cascades_and_invariants.py`, `test_06_security_and_concurrency.py`, `test_07_boundary_and_temporal.py`, `test_08_difficulty_secondary.py`

### Test count
**69 pytest functions total** (matches the 69 design tags exactly — 1:1 every test has a single verbatim `Design: ...` line)
- test_01_entities_crud.py: 10
- test_02_state_machines.py: 11
- test_03_calculations.py: 7
- test_04_validations.py: 11
- test_05_cascades_and_invariants.py: 6
- test_06_security_and_concurrency.py: 4
- test_07_boundary_and_temporal.py: 4
- test_08_difficulty_secondary.py: 16

### Instances translated
- **Difficulty queue (queue A)**: 18 / 18 instances translated, each covered by exactly 2 tests = 36 difficulty-tagged tests.
- **Corner queue (queue B)**: 33 / 33 non-stub instances translated (1 test each).
- **Stubs (8 total) correctly NOT translated** — the cited difficulty-design instance owns the assertion (contribution_post_bubble_to_state_tax_incentive_aggregate; withdrawal_disburse_bubble_to_form_1099q; contribution_post_reverse_compensation_invariant; k12_excess_calc_boundary_tested_via_difficulty_design; every_error_is_triggerable_audit; rate_threshold_k12_cap_boundary; derived_field_account_balance_reconciles_after_contribution; dual_variant_earnings_ratio_pre_vs_post).

### Instances skipped (PRD-first filter)
**None.** Every non-stub instance from both indices found verbatim coverage in PRD.md with unique derivability, so all were translated as tests.

### Coverage notes
- Every test docstring ends with exactly one `Design: Difficulty/<rule>/<instance>` or `Design: Corner/<section>/<instance>` line copied verbatim from the source yaml's `name:`.
- Identity threading: every AccountOwner-gated call uses `make_account_owner_headers(donor["id"])`, never the shared constant.
- The `auth_segregation_beats_state_occ_on_beneficiary_change_approve` test is properly designed: same X-User-ID is used both as AccountOwner (creating the change) and ComplianceOfficer (approving) — segregation must fire first per PRD §2.8 (priority 3) ahead of OCC (priority 7).
- The `beneficiary_change_to_other_family_rejected` test accepts either /create or /approve as the rejection point (PRD §3.7 says "the same rule also rejects creation"), without weakening the assertion.
- No `pytest.mark.skip`, `skipif`, or `xfail` anywhere. No scaffold references in comments/docstrings (only PRD section references).

## Step 6: Generate implementation — 2026-05-27T01:10:00Z

**Location**: `tasks/task_0004_529_college_savings/workspace/implementation/`

**File count**: 21 files (19 Python modules + `start.sh` + `requirements.txt`), 2,117 total lines.

### Layout

| Module | Lines | Purpose |
|---|---|---|
| `start.sh` | 6 | `cd $(dirname)`, `pip install -q -r requirements.txt`, `exec python3 app.py` |
| `requirements.txt` | 2 | flask 3.0.3 + python-dateutil 2.9 |
| `app.py` | 64 | Flask factory, ApiError handler, 404/405/HTTPException handlers, binds `0.0.0.0:$PORT` (default 10000) |
| `db.py` | 81 | `Store` dataclass (8 entity dicts + `withdrawal_submitter` + `bchange_creator` + `clock_utc`), `new_id`, `iso_ms`, `stamp_create`, `stamp_update` |
| `errors.py` | 62 | `ApiError`, 18 error-ID constants, HTTP-status map, `err()` factory |
| `response.py` | 129 | `success_object`/`success_array`/`error_response`; `parse_pagination` (limit 1-100, default 10) |
| `middleware.py` | 54 | `current_role`/`current_user_id`, `require_roles(*)` decorator enforcing `ERR_UNAUTHENTICATED` → `ERR_FORBIDDEN` order |
| `validators.py` | 79 | Input-shape helpers including `must_exist` (distinguishes path vs body FK) |
| `calculations.py` | 106 | `Decimal`/`ROUND_HALF_UP` implementations of all 4 calculations |
| `services.py` | 145 | `advance_by_cadence`, `recompute_account_ledger`, `recompute_state_tax_incentives`, `refresh_form_1099q_aggregates`, `refresh_matching_draft_forms_on_disburse` |
| `routes/*` | ~1500 | 11 route modules covering all 51 endpoints |

### How state machines / OCC / calculations are wired

- **State machines** in route handlers. Every transition checks from-state per §1.2, raises `ERR_INVALID_STATE` (409) on mismatch, calls `stamp_update` on the entity + cascades.
- **OCC** on `POST /withdrawals/{id}/approve` and `POST /beneficiary-changes/{id}/approve`. Order on `/approve`: SoD (3) → state (6) → OCC (7) → balance (15).
- **Calculations** are pure `Decimal`/`ROUND_HALF_UP` functions, called from `/approve` in fixed order: `earnings_ratio_split` → `k12_excess_cents` → `excess_withdrawal_penalty_cents`. The audit endpoint re-invokes `earnings_ratio_split` against current totals without writing back.

### Deliberate design notes

1. **Account ledger is re-derived from primary sources** on every mutation; guarantees the invariant `total_earnings == account_balance - total_basis`.
2. **`_market_credit_cents` is private** — stored under underscore key, never exposed in response view, added inside `recompute_account_ledger`.
3. **No startup seeding** — `Store()` initializes every dict to empty; `clock_utc` defaults to `2026-01-01T00:00:00Z`.
4. **`clock_utc` is the source of truth** for every timestamp written into entities.
5. **MONTHLY/QUARTERLY cadence uses `dateutil.relativedelta`** for calendar-month arithmetic.
6. **Smoke-tested live** through custodian → donor → beneficiary → account → contribution → market-credit → withdrawal flow plus NY state-tax-incentive flow.

## Step 7: Iterate tests + fixes — 2026-05-27T01:35:00Z

All 8 rounds pass cleanly. Exiting with summary.

---

## Summary

- **Iterations run**: 3 (initial diagnosis sweep + one fix iteration + clean confirmation sweep).
- **Tests deleted**: none. No PRD-silence findings.
- **Fixes applied to `test_helpers/`**: none.
- **Fixes applied to `implementation/`**: none.
- **Fixes applied to `test_suite/`**:
  - `test_suite/test_03_calculations.py` :: `test_excess_withdrawal_penalty_multi_input_nonlinear` — fixed two cases of reading the WRONG entity's `version` field as `expected_account_version`. The test was treating `create_and_post_contribution(...)["version"]` and `disburse_withdrawal(...)["version"]` (i.e., the Contribution row's and Withdrawal row's own envelope versions) as if they were the Account's version. Replaced both with explicit `get_account(account_id)["version"]` reads after each ledger-bumping mutation, so `expected_account_version` truly reflects the Account's version per PRD §2.7 (OCC on Account).

Diagnostic protocol: STEP 1 confirmed PRD §2.7 verbatim covers `expected_account_version`/`ERR_STALE_ACCOUNT_VERSION` and uniquely determines the rule. STEP 2 found the test's setup was inconsistent with PRD (passing a non-Account version into an OCC-on-Account check) — fix lived in `test_suite/`. STEP 3 not needed: PRD-faithful implementation was already correct.

Final result: 69/69 tests pass across all 8 parallel rounds.

## Step 8: Finalize PRD — 2026-05-27T01:40:00Z

- PRD.md: 293 lines
- PRD_FINALIZED.md: 293 lines
- Line-count delta: 0 lines (0.00%)

Changes: None.

Rationale: The only Step 7 action was a pure fixture bug fix in `test_suite/test_03_calculations.py` where the test was passing `Contribution.version` and `Withdrawal.version` as `expected_account_version` for an OCC-on-Account check. Per the step_7_diff itself, "STEP 1 confirmed PRD §2.7 verbatim covers `expected_account_version`/`ERR_STALE_ACCOUNT_VERSION` and uniquely determines the rule," and no PRD-silence findings were recorded. No fixes were applied to `implementation/` or `test_helpers/`, so the implementation is already PRD-faithful and no behavior choice was pinned by the implementation that PRD left open. PRD_FINALIZED.md is therefore an exact copy of PRD.md.


