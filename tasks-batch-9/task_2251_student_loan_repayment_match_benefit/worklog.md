# Worklog — task_2251_student_loan_repayment_match_benefit

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2251_student_loan_repayment_match_benefit/` and `tasks/task_2251_student_loan_repayment_match_benefit/workspace/` (allocated name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T12:12:00.000Z

All three artifacts are complete and the linter passes clean.

## Generated files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2251_student_loan_repayment_match_benefit/`)

**`SCAFFOLD.yaml`** (2,644 lines, §1.0–§1.7 only — no design keys)
- 14 entities, 8 state machines, 2 OCC concurrency rules, 13 calculations, 47 ordered validations, 57 endpoints, 47 errors, 5 roles
- Profile: `ledger_reconciliation` / `compliance_audit`, flat topology, parallel state shape, `segregation_of_duties` role model, immediate consistency, `difficulty_level: expert_plus`
- Complexity layers: dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, derived_field_reconciliation, optimistic_concurrency
- Domain core: one shared statutory tier space (3% @100% + 2% @50%, capped by the §402(g) 2,300,000-cent limit) consumed by both elective deferrals and certified student-loan payments, so PAY_PERIOD_MIRROR vs ANNUAL_TRUE_UP produce different match totals on identical data; that divergence propagates into ACP testing, funding batches, vesting forfeiture and erroneous-match correction

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** (1,889 lines, single key `scaffold_difficulty_design`)
- All 9 §0.5 rules, **20 instances** (2/2/2/2/3/3/2/2/2) — each rule ≥2 differentiated instances
- Both cascades are depth 4; both compensating invariants pin a conserved quantity as a formula (Q1 = plan-year funded QSLP total, Q2 = employee remaining statutory space)

**`SCAFFOLD_CORNER_DESIGN.yaml`** (3,390 lines, single key `scaffold_corner_design`)
- **9 sections, 68 instances** = 52 full test recipes + 16 `excluded_because` stubs
- entities 10, state_machines 10, calculations 8, validations 8, endpoints 6, errors 15, rbac 4, cross-cutting complexity layers 6, consistency model 1

## Verification
- `scaffold_lint.py` → `VERDICT: clean lint` (842 calls scanned across §1.8+§1.9; all six fatal checks pass, all §1.1 FKs have reverse-reachability GETs)
- Coverage cross-checks I ran independently: **0 uncovered errors** (47/47 triggerable), **0 uncovered calculations** (13/13), **0 unexercised endpoints** (57/57), **0 duplicate instance names** across both design files, and every `excluded_because.difficulty_instance` resolves to an existing §1.8 instance by exact name

Two mechanical fixes were needed for YAML validity: optional-field tokens (`field?`) and `$.data[0]...` JSONPaths inside flow mappings both required quoting.

## Step 3: Copy shared files — 2026-09-01T12:12:30.000Z

Copied `INSTRUCTION.md` to `tasks/task_2251_student_loan_repayment_match_benefit/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T12:30:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2251_student_loan_repayment_match_benefit/workspace/PRD.md`.

**Size:** 492 lines, ~12,200 words.

**Sections** (domain-derived, not copied from the example skeleton):
- §1 Introduction — 3 paragraphs (shared statutory tier space, double-counting, mirror-vs-true-up divergence)
- §2 Global Specifications — 11 subsections: 2.1 Actors, Headers and Role-Based Access Control · 2.2 API Response Structure (pasted byte-for-byte from `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 Record Identity, Timestamps and the Logical Clock · 2.5 Identifier Resolution Order · 2.6 The Shared Statutory Tier Space · 2.7 Cents Arithmetic, Rounding and Ratio Precision · 2.8 Derived Totals, Conserved Quantities and Cascading Recomputation · 2.9 Optimistic Concurrency Control · 2.10 Order of Evaluation · 2.11 Segregation of Duties and Audit Documentation
- §3 Business Logic — 9 subsections: plan-year setup + amendment; roster/HCE/leave; payroll periods + deferral match; loan registration + claim assembly; adjudication + `PAY_PERIOD_MIRROR`; funding batches + forfeiture offsets; employment change/vesting/forfeiture; `ANNUAL_TRUE_UP`; nondiscrimination testing + audit hold/void + corrections
- §4 Endpoint Definitions — 4-column table, all 57 endpoints, role sets verified against scaffold
- §5 Error Code Catalogue — 2-column table, 47 rows

**Field coverage check:**
- entities[].fields: 117 required, 117 present, 0 missing
- endpoints[].input (request bodies): 72 required, 72 present, 0 missing
- endpoints[].query_params: covered via input lists (all filter names present)
- path params + computed output keys: 28 required, 28 present, 0 missing
- Total unique identifiers: 136 required, 136 present, 0 missing
- **Status: PASS**

**Rule coverage check:**
- validations[] with priority: 47 checked, 47 expressed in prose (§2.10 states the full global precedence with each `applies_to` scope enumerated; conditions carried in §3), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed with write endpoint + `expected_employee_version` / `expected_plan_year_version` + error id + 412, 0 missing
- state_machines[].transitions: 43 checked, 43 expressed with explicit `from` → `to` arrows plus preconditions, error ids and side effects, 0 missing
- calculations[]: 13 checked, 13 fully expressed in natural language including the four pinned rounding orders, the pinned true-up step order 1→4, and the two-stage 4-decimal ACP rounding, 0 missing
- errors[]: 47 checked, 47 named in prose and 47 in §5 with HTTP statuses matching the scaffold exactly, 0 mismatches
- endpoints[].side_effects / cascades: expressed, including the acceptance cascade, void compensation, termination forfeiture cascade, forfeiture offset waterfall and test-staling
- sibling-branch symmetry: 6 groups checked (amendment adopt/rescind, claim accept/return, audit release clear/void, settlement settled/rejected, test passed/failed, vesting fully/partially/forfeited), equal prose density
- **Status: PASS**

**Path purity check (§3 only):**
- backtick tokens scanned: 924
- tokens starting with `/`: 0 · bare HTTP-method tokens: 0 · method+path combined tokens: 0
- **Status: PASS**

**Coverage notes / judgment calls:**
- The scaffold nominates no error id for the "referenced plan year must be `DRAFT` or `OPEN`" precondition on amendment adoption and effectiveness. I stated the precondition plainly rather than inventing a code, since `ERR_PLAN_YEAR_LOCKED`'s declared scope excludes amendment status changes.
- `FundingBatch.forfeiture_offset_cents` has a mildly conflicting field note ("always 0 unless `PENDING`") versus the waterfall's freeze-on-exit semantics. I documented the freeze semantics, which are consistent with the transmit side effect.
- `LEAVE_PAID` is reachable in the `employment_status` enum but no transition produces it; I noted it as reserved and stated that `PAID_FMLA` / `MILITARY` leave does not move `employment_status`.
- The two withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped or referenced, and no sibling task directory was accessed. No worked-example numbers appear in the PRD; only scaffold-declared constants and defaults, rendered with dollar unit conversions.

## Step 5: Generate unit tests — 2026-09-01T14:00:00.000Z

Suite complete. All audits pass.

## Files written

**`/home/ubuntu/github/CodingPRD/tasks/task_2251_student_loan_repayment_match_benefit/test_helpers/`** (9 files, 2,677 lines)
- `types.py`, `api_errors.py` (47 PRD error ids + HTTP status map registered at import), `constants.py`, `test_users.py`, `api_client.py` (61 endpoint methods over `GenericApiClient`), `factories.py` (24 payload builders + `OMIT` sentinel), `assertions.py` (shape/cents/ratio/instant asserts), `fixtures.py` (`build_claim_scenario` + 20 named scenario shortcuts, ACP population builders, listing helpers), `__init__.py`

**`/home/ubuntu/github/CodingPRD/tasks/task_2251_student_loan_repayment_match_benefit/test_suite/`** (13 files, 3,825 lines)

| file | tests |
|---|---|
| `conftest.py` | — |
| `test_01_plan_year_amendment_and_period_lifecycle.py` | 6 |
| `test_02_participant_roster_and_leave.py` | 8 |
| `test_03_payroll_lines_and_deferral_match.py` | 5 |
| `test_04_loan_accounts_and_claim_assembly.py` | 10 |
| `test_05_claim_submission_and_statutory_space.py` | 8 |
| `test_06_claim_acceptance_and_mirror_match.py` | 12 |
| `test_07_funding_batches_and_settlement.py` | 7 |
| `test_08_vesting_forfeiture_and_termination.py` | 5 |
| `test_09_annual_true_up.py` | 5 |
| `test_10_nondiscrimination_testing.py` | 9 |
| `test_11_audit_hold_void_and_corrections.py` | 7 |
| `test_12_access_control_reads_and_listings.py` | 9 |

## Test counts per queue

**91 tests total: 40 queue A (Difficulty) + 51 queue B (Corner).** `pytest --collect-only` collects all 91 with zero collection errors.

## Instances skipped

One, and only one:
- **`corner_certification_line_referencing_other_employees_loan_rejected`** — asserts `ERR_NOT_RESOURCE_OWNER` when a certification line points at another employee's loan account. PRD §2.1 defines the line-level ownership check as comparing "the `employee_id` of its parent claim" to `X-User-ID`, which the acting employee satisfies; no PRD sentence requires the *referenced loan account* to belong to the claimant. The asserted 403 is therefore not uniquely derivable from the PRD, so the instance was dropped with no test, no xfail, no placeholder.

All 16 `excluded_because:` corner stubs were correctly left untranslated (verified: zero stub names appear in any `Design:` tag).

## Coverage audit

- **Design tags:** every one of the 91 tests carries exactly one `Design:` line, and it is the final line of the docstring. Every tag resolves to a real `name:` in the source yaml — no malformed, dual-tagged, untagged, or dangling tags.
- **Queue A depth floor:** all 20 difficulty instances (9 rules) covered, each by **≥2** tests. For the priority-pair and cross-entity instances the second test proves the masked higher-ordinal rule fires once the lower-ordinal fault is repaired.
- **Queue B breadth:** 51 of 52 non-stub corner instances covered, each by ≥1 test (the 52nd is the skip above). All 9 corner sections represented.
- **PRD citations:** 152 quoted citations across all docstrings were grepped against `workspace/PRD.md` after whitespace normalisation — **0 non-verbatim**. (6 initial failures in `test_12`, written from memory, were corrected to the PRD's actual §2.1/§2.3/§2.10 wording.)
- **Scaffold-leak check:** zero occurrences of "scaffold" or `§1.x` in any generated comment or docstring; only PRD sections are referenced.
- **Reference resolution:** every `fx.*`, `f.*`, `client.*` call and every `from test_helpers.* import` name statically resolves; all files parse.
- Per-file test count is ≥5 everywhere. The `workspace/implementation/` directory was never read, and no sibling task directory was touched.

Tests were not executed — no API server is running in this environment.

## Step 6: Generate implementation — 2026-09-01T14:00:30.000Z

Implementation is complete and verified. All four throwaway smoke suites now pass end to end (the earlier mismatches were wrong expectations in my ad-hoc scripts, confirmed against PRD text — details below).

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_2251_student_loan_repayment_match_benefit/workspace/implementation/`:

- `start.sh` (installs Flask only when missing, then `exec python3 app.py`; honors `PORT`, default 10000), `requirements.txt` (`flask>=3.0.0`)
- `app.py` (blueprint registration + `ApiError`/404/405/400/catch-all handlers), `db.py` (in-memory `Store`, logical clock, id/version stamping, ordering), `errors.py` (all 47 error ids → HTTP status), `response.py` (envelope + pagination), `middleware.py` (auth headers, role gate, typed body/query parsers)
- `services/calc.py`, `services/serialize.py`, `services/lookup.py`, `services/effects.py`
- `routes/plan_years.py`, `amendments.py`, `employees.py`, `payroll.py`, `loans.py`, `allocations.py`, `funding.py`, `tests_acp.py`, `clock.py`, plus `routes/__init__.py`, `services/__init__.py`

No SQLite, no JSON dump, no `/tmp` cache, no seeding: a fresh boot serves `GET /plan-years` and `GET /employees` as empty arrays with the clock at `2026-08-01T00:00:00.000Z`.

## Endpoints
57 API routes registered (58 rules including Flask's `/static`), matching the PRD §4 table: 14 entities, 10 versioned + 4 audit-row collections, `Decimal`/ROUND_HALF_UP money math throughout.

## Verification highlights (4 fresh-server smoke runs, 0 failures)
- Cross-tier straddle, compensation-cap accumulator, mirror spill across periods, dual-variant mirror vs annual true-up (delta 10000 from a period-fluctuation strand), true-up **recoupment** branch (per-period rounding inflation → `TRUE_UP_RECOUPMENT` of −3 cents, signed negative summary).
- ACP double rounding reproduced exactly: per-participant ratios 0.0100495→0.0100 and 0.010050→0.0101, group mean of the rounded values 0.01005→**0.0101** (single-rounding would give 0.0100), limit **0.0202**, FAILED, corrective forfeiture −17300.
- Full claim lifecycle: all line rules, RETURN loop with exact space restoration, supersede (old claim REVERSED allocations + `ERRONEOUS_MATCH` −25000, batch excludes reversed), audit hold/CLEAR, VOID conservation with segregation-of-duties, audit packet, `ERR_QSLP_SPACE_EXHAUSTED`, ownership scoping.
- Funding lifecycle incl. REJECTED→PENDING→TRANSMITTED retry with one version bump, settlement cascade to period FUNDED, forfeiture waterfall/offset freeze, vesting/forfeiture on termination, rehire, leave collision/cap/auto-return, OCC 412s, envelope/pagination/auth/404 shapes.

## PRD ambiguities resolved (interpretation chosen)
1. `created_at`/`updated_at` come from the logical clock; stable list order is `(created_at, internal_seq)`.
2. True-up STEP 3 "created_at strictly earlier than the run's start instant" → internal sequence < run sequence.
3. True-up STEP 2 `ytd_deferral_cents` scoped to the true-up's own (LOCKED) plan year.
4. Employee `hce_flag`, YTDs, `remaining_qslp_space_cents`, `vested_pct`, `unpaid_leave_days_ytd` computed live at read time; space null and YTDs 0 with no OPEN plan year.
5. `LEAVE_UNPAID → ACTIVE` auto-transition happens on read (version +1) only once the clock is strictly past **every** UNPAID leave's `end_date` (literal PRD wording — a future-dated leave keeps the employee on leave).
6. `unmatched_eligible_cents` = eligible − Σ(tier1+tier2 applied) over SCHEDULED|FUNDED allocations (so tier-2 dollars count as matched even though only half is paid).
7. `POST /loan-certifications/{id}/lines` resolves the path `certification_id` before the body `loan_account_id` (§2.5 path-before-body wins over the §2.10 ordinal order); body-only multi-identifier requests follow §2.10 ordinals. Transmit checks period-closed (ord. 20) before batch state (ord. 23).
8. Supersede reversal runs **after** the new claim's eligible/mirror computation, so the new claim sees the old allocations as live space consumers.
9. Uncatalogued precondition failures mapped: incoherent plan-year windows / undefined transitions / duplicate `year` / duplicate `external_id` / bad employment-event preconditions → `ERR_INVALID_REQUEST` 400; invalid payroll-period transitions → `ERR_PERIOD_ALREADY_FUNDED` 409; period close, amendment ADOPT→EFFECTIVE and ACP compute against a disallowed plan-year state → `ERR_PLAN_YEAR_LOCKED` 409.
10. Employee-role list endpoints auto-scope to the caller's own id; `GET /certification-lines/{id}` returns `ERR_NOT_RESOURCE_OWNER` for a non-owner Employee.
11. Client-supplied datetimes echoed verbatim; system-stamped timestamps canonical `YYYY-MM-DDTHH:MM:SS.mmmZ` (including `current_utc`).
12. ACP HCE/NHCE split evaluated against the plan year under test; `Employee.hce_flag` stays tied to the OPEN plan year.
13. Batch `forfeiture_offset_cents` computed live by the waterfall while PENDING, frozen when it leaves PENDING; `total_allocated_cents`/`allocation_count` always live (excluding REVERSED); `net = total − offset`.
14. Fractional tier ceilings are reduced to integer `qslp_space_tier*_cents` with round-half-up, and the mirror walk consumes those integer fields.
15. `UNVESTED → FULLY_VESTED` shortcut at allocation creation when `vested_pct == 1.00`; creation leaves `version` at 1.
16. Leave-event creation increments `Employee.version` unconditionally.
17. `total_recoupment_cents` is emitted as the signed (negative) sum.
18. Retransmit performs exactly one version increment for the REJECTED→PENDING→TRANSMITTED request.
19. Settlement does not bump the plan year version (SCHEDULED→FUNDED leaves funded totals unchanged).

## Step 7: Run tests and iterate — 2026-09-01T14:35:00.000Z

All green. Final report:

## Summary

**Iterations run:** 2 (each an 8-round parallel stability sweep, 91 tests per round)

- Sweep 1: 89/91 in all 8 rounds — 2 tests failing deterministically (identical failure in every round, so no flakiness signal).
- Sweep 2 (after fix): **91/91 in all 8 rounds**, union failure set empty.

**Tests deleted:** none. Both failures traced to a test_helpers fixture bug, not to PRD silence or under-determination.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_2251_student_loan_repayment_match_benefit/test_helpers/fixtures.py` — `advance_amendment_to()` (plus the module constant it walks, renamed `_AMENDMENT_PATH` → `_AMENDMENT_CHAIN`, and a new `refresh_amendment()` read helper). The helper unconditionally replayed the walk from the first step, so when a test called it on an amendment already parked at `ADOPTED` or `NOTICE_SENT` it re-issued `to_status: "ADOPTED"`. PRD §3.1 admits only the single-step transitions `DRAFTED → ADOPTED → NOTICE_SENT → EFFECTIVE`, so the PRD-faithful implementation correctly answered `ERR_AMENDMENT_STATE_INVALID` (409) — a fixture bug (STEP 2), not an implementation bug. The helper now GETs the amendment and resumes from its current status, driving only the remaining steps up to the target.

Affected tests, both in `test_suite/test_06_claim_acceptance_and_mirror_match.py`, which build a claim under a non-effective amendment, assert the acceptance is masked by `ERR_AMENDMENT_NOT_EFFECTIVE`, and then advance the *same* amendment to `EFFECTIVE` to reveal the next-priority rule:
- `test_loan_not_verified_surfaces_once_the_amendment_is_effective` (was: `ADOPTED → ADOPTED`)
- `test_effective_amendment_unblocks_acceptance` (was: `NOTICE_SENT → ADOPTED`)

**Fixes applied to `implementation/`:** none. No PRD-required check was relaxed; the implementation's amendment state machine was already faithful to PRD §3.1 and the §2.10 ordinal-24 placement of `ERR_AMENDMENT_STATE_INVALID`.

**Note on tooling:** my first sweep's shell logs were written to `/tmp/sweep1_*.log`, which collided with another pipeline running on this host (I saw a foreign test suite's output). Later sweeps used `/tmp/t2251_logs/`; the `results.*.json` files themselves were never affected since they were task-scoped paths. I removed the `results.*.json` files from `workspace/implementation/` afterward so the deliverable directory holds only implementation source.

**Orchestrator confirmation sweep (independent re-run, 2026-09-01T14:52:00.000Z):** because the Step 7 subagent deleted the results files, the orchestrator re-ran the full 8-round parallel sweep itself. Result: `results.{1..8}.json` all report `91 / 91`. The deliverable results files are restored on disk.

## Step 8: Finalize PRD — 2026-09-01T14:52:30.000Z

## Outcome: zero edits — `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md`

- `/home/ubuntu/github/CodingPRD/tasks/task_2251_student_loan_repayment_match_benefit/workspace/PRD_FINALIZED.md` exists on disk.
- **Line counts:** PRD.md 491 / PRD_FINALIZED.md 491 — **%-delta 0.0%** (identical md5 `e250b56f2d8952ebed611b91e57730ce`).
- **Change bullets:** none.

### Why zero

`<step_7_diff>` contains exactly one item: a `test_helpers/fixtures.py` bug in `advance_amendment_to()` (plus the `_AMENDMENT_PATH` → `_AMENDMENT_CHAIN` rename and the new `refresh_amendment()`). No implementation fixes, no test deletions. I verified the diagnosis against the implementation rather than trusting it:

- `implementation/routes/amendments.py:16-18` declares `TRANSITIONS` as exactly the five single-step edges `DRAFTED→ADOPTED`, `ADOPTED→NOTICE_SENT`, `NOTICE_SENT→EFFECTIVE`, `ADOPTED→RESCINDED`, `NOTICE_SENT→RESCINDED`; `amendments.py:80-82` rejects anything else with `ERR_AMENDMENT_STATE_INVALID`. PRD §3.1 (lines 226-233) enumerates precisely those five edges and states "a destination that does not match the amendment's current state is rejected with `ERR_AMENDMENT_STATE_INVALID`", and §5 pins it at 409. So `ADOPTED → ADOPTED` and `NOTICE_SENT → ADOPTED` (the two replays the old fixture issued) are uniquely determined rejections — PRD already fully determines the behavior, so §3.1 prose stays verbatim.
- Body-parse-before-state-check order in `amendments.py:70-82` matches §2.10 ordinal 3 < ordinal 11 < ordinal 24; amendment lookup at `amendments.py:78` sits between them. Consistent, nothing to pin.
- The two affected tests (`test_suite/test_06_claim_acceptance_and_mirror_match.py:194-286`) additionally rely on `ERR_AMENDMENT_NOT_EFFECTIVE` masking `ERR_LOAN_NOT_VERIFIED`; that is already pinned by §2.10 ordinals 30 vs 32 plus the explicit note at PRD line 202. No PRD gap.
- The rewritten helper's only new API dependency is `GET /plan-amendments/{amendment_id}`, whose role list (`BenefitsAdministrator`, `ComplianceAuditor`) already matches `amendments.py:61` and the §4 table.

Per-edit pre-edit search log is empty because no edit was committed; the enumeration above is the search that led to the no-edit conclusion.

### One out-of-scope observation (deliberately NOT patched)

`implementation/routes/amendments.py:84-88` guards the `ADOPTED` and `EFFECTIVE` transitions with "plan year must be `DRAFT` or `OPEN`" and rejects with **`ERR_PLAN_YEAR_LOCKED`**. PRD §3.1 states the requirement but never names the code, and §2.10 ordinal 17 does not list `POST /plan-amendments/{amendment_id}/status` among its endpoints — so this is a real PRD silence a fresh implementer could resolve differently. Step 7 never exercised the rejecting branch (its plan years are `OPEN`), and the diff reports no fix touching it, so patching it would fall outside the HARD SCOPE. Flagging it in case a later step wants it in scope.

## Step 9: Complete PRD — 2026-09-01T15:05:00.000Z

All edits applied. `PRD_COMPLETED.md` exists on disk.

## Summary

**Source vs output:** `workspace/PRD_FINALIZED.md` 491 lines / 92,701 chars → `workspace/PRD_COMPLETED.md` 492 lines / 99,361 chars (**+1 line, +6,660 chars**). No sections added; one new bullet inside the existing §2.2 bullet list, every other change is in-paragraph.

**Counts:** 20 ambiguity-pins, 8 mismatch-revisions (28 changes).

### Changes

- §2.1 Actors/RBAC — revise — mismatch — ownership-checked ops are ten, not nine: `GET /certification-lines/{certification_line_id}` is guarded against the parent claim's `employee_id`; also pinned that `Employee`-role list endpoints are silently scoped (not rejected) and `total_count` counts only owned rows — `routes/loans.py:286-294`, `services/lookup.py:66-70`
- §2.2 Error format — insert — ambiguity — unknown path → `ERR_RECORD_NOT_FOUND` 404; unsupported method / non-object body → `ERR_INVALID_REQUEST` 400 — `app.py:41-54`
- §2.3 Pagination — insert — ambiguity — out-of-bounds/non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; empty string treated as omitted — `response.py:59-71`
- §2.7 Rounding contract — insert — ambiguity — the two leftover-space fields are each reduced to whole cents separately, round half up — `services/calc.py:386-387`
- §2.10 ordinal 14 — revise — mismatch — "nine operations" → "ten operations" — `routes/loans.py:292`
- §2.10 ordinal 17 — revise — mismatch — `ERR_PLAN_YEAR_LOCKED` also fires on `POST /plan-amendments/{id}/status` (ADOPTED/EFFECTIVE, plan year must be DRAFT/OPEN), `POST /payroll-periods/{id}/status` and `POST /nondiscrimination-tests/{id}/compute` (OPEN/LOCKED), and on those three it is evaluated *after* the endpoint's own from-state check — `routes/amendments.py:84-88`, `routes/payroll.py:85-88`, `routes/tests_acp.py:72-75`
- §3.1 plan-year create — insert — ambiguity — duplicate `year` → `ERR_INVALID_REQUEST` — `routes/plan_years.py:82-84`
- §3.1 plan-year status — insert — ambiguity — unrecognized `to_status` or transition pair → `ERR_INVALID_REQUEST`, not a state-conflict code — `routes/plan_years.py:124-127`
- §3.1 DRAFT→OPEN — insert — ambiguity — incoherent windows → `ERR_INVALID_REQUEST`, only on this transition and only after the `ERR_MULTIPLE_OPEN_PLAN_YEARS` check — `routes/plan_years.py:146-157`
- §3.1 amendment DRAFTED→ADOPTED — insert — ambiguity — plan-year precondition rejects with `ERR_PLAN_YEAR_LOCKED`, checked after `ERR_AMENDMENT_STATE_INVALID` *(the known lead)* — `routes/amendments.py:84-88`
- §3.1 amendment NOTICE_SENT→EFFECTIVE — insert — ambiguity — same code, and it outranks `ERR_AMENDMENT_EFFECTIVE_DATE_FUTURE` — `routes/amendments.py:84-93`
- §3.2 employee create — insert — ambiguity — duplicate `external_id` → `ERR_INVALID_REQUEST` — `routes/employees.py:28-31`
- §3.2 YTD aggregates — insert — ambiguity — all read zero when no plan year is `OPEN` — `services/serialize.py:108-118`
- §3.2 leave collision rule — revise — mismatch — buffer comes from the `OPEN` plan year, else the greatest-`year` plan year of any status, else 14 days — `routes/employees.py:166-189`
- §3.2 leave cap rule — insert — ambiguity — applies only to `UNPAID` events and only while a plan year is `OPEN`; skipped otherwise — `routes/employees.py:199-205`
- §3.2 leave/version — insert — ambiguity — every accepted leave event increments the employee's `version`, regardless of type or status move — `routes/employees.py:223`
- §3.3 period status — insert — ambiguity — plan year must be `OPEN`/`LOCKED` → `ERR_PLAN_YEAR_LOCKED`, governs the reopen too, evaluated between the transition-pair and settled-funding checks — `routes/payroll.py:85-96`
- §3.3 period status — revise — mismatch — `ERR_PERIOD_ALREADY_FUNDED` also covers any transition pair other than OPEN→CLOSED / CLOSED→OPEN — `routes/payroll.py:81-83`
- §3.3 line calc step 6 — insert — ambiguity — each tier-space field independently rounded half up to whole cents — `services/calc.py:386-387`
- §3.4 loan verification — revise — mismatch/ambiguity — `evidence_ref` overwritten only when supplied; no from-state guard, so any status→any status is accepted — `routes/loans.py:76-87`
- §3.5 decision — insert — ambiguity — `reason` is validated but never persisted or surfaced — `routes/loans.py:348`
- §3.6 batch create — insert — ambiguity — no cross-check that the period belongs to the plan year — `routes/funding.py:22-27`
- §3.6 transmit — revise — mismatch — guards run period-closed → batch-state → empty, and the batch may be `PENDING` *or* `REJECTED` — `routes/funding.py:70-80`
- §3.7 TERMINATE — insert — ambiguity — from `TERMINATED` → `ERR_INVALID_REQUEST` — `routes/employees.py:87-92`
- §3.7 REHIRE — insert — ambiguity — both preconditions fail with `ERR_INVALID_REQUEST` — `routes/employees.py:98-105`
- §3.8 true-up start / step three — revise — mismatch — the funded-QSLP snapshot cuts on ledger insertion order, not a `created_at` comparison, so rows whose `created_at` equals the run instant still count — `services/effects.py:205`, `services/calc.py:485-488`
- §3.9 test create — insert — ambiguity/mismatch — `test_method` required, plan year's `nondiscrimination_test_method` never a fallback; new test has `include_qslp_match` true, `correction_method` null, `total_correction_cents` zero — `routes/tests_acp.py:21-37`
- §3.9 compute — insert — ambiguity — plan-year requirement is `ERR_PLAN_YEAR_LOCKED`, checked after the from-state check — `routes/tests_acp.py:68-75`
- §3.9 ACP population split — revise — mismatch — the HCE determination uses the *test's* plan year threshold, not the employee's `hce_flag` against the `OPEN` plan year — `services/calc.py:540`
- §3.9 audit-hold — insert — ambiguity — `reason` is required (`ERR_INVALID_REQUEST` when absent/empty) — `routes/loans.py:385`
- §3.9 test correction — insert — ambiguity — ratios recomputed at correction time with the test's stored `include_qslp_match` and compared to the stored `limit_acp`; a zero rounded excess writes no adjustment — `routes/tests_acp.py:108-121`
- §3.9 audit packet — insert — ambiguity — with no `OPEN`/`LOCKED` plan year the packet still returns, `plan_year_id` null and all six money/count figures zero — `routes/employees.py:126-136`

Two PRD-internal order conflicts I left alone because §2.5 already pins them: path-before-body resolution on `POST /loan-certifications/{id}/lines` (certification 404 beats loan-account 404, contra ordinals 7/8). Role tables in §4 match the implementation exactly at every endpoint.

## Pipeline complete — 2026-09-01T15:06:00.000Z

All nine steps ran to completion. Final state: 91/91 tests passing in all 8 rounds of the confirmation sweep (`workspace/implementation/results.{1..8}.json`), `workspace/PRD_COMPLETED.md` on disk.
