# Worklog — task_2695_contractor_licensing_complaint_adjudication

## Step 1: Create task directory — 2026-09-04T08:05:26.153Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2695_contractor_licensing_complaint_adjudication` and `.../workspace` (pre-assigned path, index fixed by scenario number 2695; no index auto-allocation performed).

## Step 2: Generate scaffold — 2026-09-04T10:11:14.974Z

Scaffold for task 2695 is complete and lints clean.

## Files

| File | Lines | Bytes |
|---|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_2695_contractor_licensing_complaint_adjudication/SCAFFOLD.yaml` | 2444 | 161 KB |
| `/home/ubuntu/github/CodingPRD/tasks/task_2695_contractor_licensing_complaint_adjudication/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 3014 | 189 KB |
| `/home/ubuntu/github/CodingPRD/tasks/task_2695_contractor_licensing_complaint_adjudication/SCAFFOLD_CORNER_DESIGN.yaml` | 4792 | 291 KB |

All three parse under PyYAML; each ends at a clean YAML boundary. `SCAFFOLD.yaml` has exactly 13 top-level keys (`scenario` … `roles`) and contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`; the two design files each have a single top-level key. The `scenario:` value is the supplied text verbatim.

## Domain model shape (§1.0–§1.7)

- 15 entities (TradeClassification, RecoveryFundAccount, Licensee, QualifyingIndividual, ExamResult (immutable, `common_fields: false`), LicenseApplication, License, CoverageRecord, QualifierAssignment, Consumer, Complaint, Investigation, Citation, DisciplinaryHearing, RecoveryFundClaim)
- 62 endpoints, 9 state machines (License carries two independent dimensions: `status` × `compliance_posture`), 3 `concurrency_rules` (qualifier-assign / repayment on `expected_license_version`, claim pay on `expected_fund_account_version`), 8 calculations (2 dual-variant), 60 validations on a 1→83 priority ladder, 71 errors, 7 roles (BoardAdmin, LicensingAnalyst, Investigator, HearingOfficer, FundAdjudicator, Licensee, Consumer — `peer_roles`, no override)

## Design instance counts

- §1.8: 9 rule_ids, **26 instances**
- §1.9: **101 instances** across all nine claim-extraction sections — entities 13, state_machines 16, calculations 11, validations 31, endpoints 2, errors 12, rbac 8, cross-cutting complexity layers 7, consistency model 1. Of these, 77 carry a full `test_recipe` and 24 are `excluded_because` stubs, each citing a §1.8 instance verified to exist by name. All 127 names across §1.8 ∪ §1.9 are unique; no instance carries both `test_recipe` and `excluded_because`.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2695_contractor_licensing_complaint_adjudication/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2695_contractor_licensing_complaint_adjudication/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2695_contractor_licensing_complaint_adjudication/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    62
  §1.1 entities declared:     15
  §1.8 instances scanned:     26
  §1.9 instances scanned:     77
  Calls scanned (§1.8+§1.9):  1338

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Two notes worth carrying forward: the hard constraint held — nothing outside this task directory and the generator skill was read; and every literal in the recipes (renewal fees 71500/49500, penalty 312500, awards 1500000/0, balance 3500000, dates 2026-09-16, 2026-11-30, 2028-08-01, 2030-08-01, CE ceiling 40) was recomputed from the scaffold's own formulas and constants rather than assumed.

## Step 3: Copy shared files — 2026-09-04T10:11:32.410Z

Copied `./INSTRUCTION.md` to `tasks/task_2695_contractor_licensing_complaint_adjudication/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T10:27:51.796Z

PRD complete at `/home/ubuntu/github/CodingPRD/tasks/task_2695_contractor_licensing_complaint_adjudication/workspace/PRD.md` — **491 lines, 112,364 bytes**, built in 8 incremental chunks (1 `Write` + 7 `cat >>` heredocs), so no 64k-cap truncation.

**Section list**

- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 11 subsections: 2.1 Board Actors and RBAC · 2.2 API Response Structure · 2.3 Pagination · 2.4 Common Resource Properties and the Logical Clock · 2.5 Money, Percentages and Arithmetic Discipline · 2.6 The Two Dimensions of a Licence · 2.7 Coverage Periods, Designation Windows and Boundary Inclusivity · 2.8 Cascade Discipline and Hierarchical Consistency · 2.9 Presenting a Version: Optimistic Concurrency · 2.10 Segregation of Duties · 2.11 Validation Ordering and Path Resolution
- `## 3. Business Logic & Workflows` — 9 subsections: 3.1 Statutory Reference Data · 3.2 Registering the Parties / Examination Currency · 3.3 From Application to Licence · 3.4 The Qualifier of Record · 3.5 Bond and Insurance · 3.6 CE, Renewal and Reinstatement · 3.7 Complaint Intake, Screening and Mediation · 3.8 Enforcement: Investigation, Citation, Sanction Ladder · 3.9 The Consumer Recovery Fund
- `## 4. Endpoint Definitions` — 62 rows, exactly 4 columns (Method | Path | Description | Authorized Role(s))
- `## 5. Error Code Catalogue` — 71 rows, exactly 2 columns (Error ID | HTTP Status Code)

**Hard Contracts — all PASS (machine-verified)**

- **Contract 1 (field-name coverage): PASS.** Script-parsed all 15 entities' `fields[].name` plus every `request_body`/`input`/`query_params`/`path_params`/output identifier from all 62 endpoints = 141 distinct names; all 141 appear verbatim in backticks. Missing set empty.
- **Contract 2 (rule coverage): PASS.** All 71 `ERR_*` ids appear in §2/§3 prose (not merely in the §5 table); all 58 distinct validation `error_id`s covered (the 59th is the `ERR_<ENTITY>_NOT_FOUND` template, expanded to all 14 concrete 404s in §2.11); all 9 state machines' enum values present; all 3 `concurrency_rules` (both `expected_license_version` uses + `expected_fund_account_version`) in §2.9; all 8 calculations rendered as prose (`credited_experience_months`, `license_compliance_posture`, `bond_continuity_gap_days`, `renewal_fee`, `citation_civil_penalty`, `sanction_points`, `recovery_award`, `recovery_prorata_distribution`); 85 `side_effects` entries covered by the cascade passages. Independently diffed §4's 62 role lists against `endpoints[].roles` — zero mismatches — and §5's 71 statuses against `errors[].http` — zero mismatches.
- **Contract 3 (§3 path purity): PASS.** Extracted §3 (`## 3.` → `## 4.`) and scanned every backtick token: no token starts with `/`, none is a bare HTTP method, none is method+path. Endpoints referenced only by state-transition framing, role+verb, or capability.

Additional checks: §2.2 is byte-verbatim against `section-2.2-response-structure.md`; zero pseudocode operators (`==`, `>=`, `&&`, `COALESCE`, `CASE WHEN`); zero fuzzy words ("approximately", "roughly", "conservatively"). The only scaffold UPPER_SNAKE tokens absent from the PRD are the symbolic constant names themselves (`HAZARD_STEP`, `PRIOR_STEP`, `MAX_MEDIATION_ROUNDS`, …), which is required — their values are stated as prose numbers.

**One real bug found and fixed during the audit:** §3.6 had rendered `CE_SHORTFALL_FEE_CENTS_PER_HOUR: 5000` as "500 dollars — 50,000 cents" (10x too high), which also made the worked example internally inconsistent ("four times 50,000, or 65,000"). Corrected to "50 dollars — 5,000 cents" and "four times 5,000, or 65,000". A follow-up sweep of every dollar/cent figure in the document confirmed all remaining pairs are consistent and match the scaffold constants (jurisdictional minimum 500 dollars/50,000 cents, fund tier threshold 1,000 dollars/100,000 cents, statutory max 15,000 dollars/1,500,000 cents, severity bases 500/2,500/7,500 dollars, penalty examples 375,000/525,000/393,750/2,250,000→1,500,000, recovery examples 1,200,000/300,000/900,000/1,100,000 and pro-rata 572,728/327,272).

**Tail is complete** — the file ends on the final `| \`ERR_CLAIM_EXCEEDS_ALLEGED_LOSS\` | 422 |` row of the §5 table, a real section boundary, not mid-sentence.

**Access confirmation:** neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced at any point, and no sibling task directory under `/home/ubuntu/github/CodingPRD/tasks/` was read. Sources were limited to `SCAFFOLD.yaml`, the three skill files, and the PRD itself. All Hard Contract reports live only in this message — nothing was written into PRD.md or any sibling file.

**Orchestrator verification (truncation guard):** independently confirmed 491 lines, 5 top-level sections at lines 3/11/178/346/415, and the tail ending on a complete §5 table row. Also grepped PRD.md for "expert level" — 0 hits, so the Step 2 difficulty instruction did not leak into the PRD.

## Step 5: Generate unit tests — 2026-09-04T11:25:02.290Z

Suite is complete and verified.

## What was produced

**Location (confirmed at task root, nothing under `workspace/`):**
- `/home/ubuntu/github/CodingPRD/tasks/task_2695_contractor_licensing_complaint_adjudication/test_helpers/` — 9 files, **2728 lines** (`__init__.py` 233, `api_client.py` 331, `api_errors.py` 181, `assertions.py` 304, `constants.py` 126, `factories.py` 352, `fixtures.py` 698, `test_users.py` 74, `types.py` 429)
- `.../test_suite/` — `conftest.py` (54) + 25 test modules, **8464 lines total**, **159 tests**

Queue A (difficulty index, written by me): test_01 491/8, test_02 238/5, test_03 384/7, test_04 240/6, test_05 315/6, test_06 223/5, test_07 434/7, test_08 278/6, test_09 296/6, test_10 352/7, test_11 333/6 -> 69 tests.
Queue B (corner index, four partitioned subagents): test_21 258/6, test_22 378/7, test_23 289/5, test_24 436/6, test_30 189/6, test_31 401/9, test_32 151/5, test_40 357/7, test_41 217/5, test_42 648/10, test_50 409/7, test_51 263/6, test_52 389/5, test_53 441/6 -> 90 tests.

## Design-index coverage (machine-verified against both yamls)

- **26/26 difficulty instances translated**, **77/77 non-stub corner instances translated** = 103 of 103 non-stub instances. **Zero instances skipped.**
- The 24 corner instances with no test are exactly the 24 carrying an `excluded_because:` block (stubs subsumed by a §1.8 instance) — verified programmatically, all 24 have that key.
- Every `def test_` (including the 10 class-method tests in test_42) carries exactly one `Design:` line; every tag resolves to a real instance under the real section name (`bad: []`), including the space-bearing sections `cross-cutting complexity layers` and `consistency model`.
- No `skip`/`skipif`/`xfail`/`pytest.mark`, no mocking, no occurrence of "scaffold" or §1.8/§1.9 anywhere in the emitted code.

## Verification run

- `python3 -m py_compile` on all 9 helper files and all 26 suite files: **all pass**; `__pycache__` cleaned up afterwards.
- `python3 -m pytest test_suite --collect-only -q` -> **159 tests collected, 0 errors** (so `test_helpers` imports cleanly and every module is importable).
- All `ApiErrorId.*` references resolve to declared members (`missing: set()`); all raw `"ERR_*"` literals exist in `ERROR_HTTP_STATUS`.

## Key finding fixed this session

`test_helpers/api_client.py` had a latent break in **all 10** list/params calls: `self.get(path, params or {}, headers=headers)` against the framework signature `get(self, path, headers=None, params=None, **kwargs)` -> `TypeError: got multiple values for argument 'headers'`. This would have failed `list_licenses/list_complaints/list_citations/list_qualifier_assignments/list_exam_results/...` and, through them, the fixtures `find_license_for_application`, `find_assignment_for_license`, `mint_active_license`, `substantiated_citation`, `appealed_citation_with_hearing` — i.e. nearly every test in the suite. All 10 call sites now pass `params=params or {}` by keyword. (Queue B's `_list_rows` helpers, which called `api.get(..., headers=..., params=...)` directly, were already correct and are unaffected.)

Two other notes worth keeping: `ApiErrorId` members are declared without the `ERR_` prefix (so `.value` is needed for `!=` comparisons against a returned `error_id`), and creation endpoints returning 201 must go through `get_success_data`, not `validate_success` (which defaults to 200). Both are honored throughout. Nothing under `workspace/implementation/` was read or created, and no sibling task directory was touched.

**Orchestrator verification:** `test_helpers/` (9 .py) and `test_suite/` (26 .py) confirmed at the task root; `find workspace -maxdepth 2` for stray `test_helpers`/`test_suite` returned nothing, so the known "test dirs land under workspace/" failure mode did not occur.

## Step 6: Generate implementation — 2026-09-04T11:25:02.290Z

Smoke server terminated (recorded wrapper PID 188114 plus its python3 child 188116, verified as the only listener on port 18795; port now free, no pattern-kill used).

## Implementation delivered

`/home/ubuntu/github/CodingPRD/tasks/task_2695_contractor_licensing_complaint_adjudication/workspace/implementation/`

| file | lines | role |
|---|---|---|
| `core.py` | 538 | logical clock, empty in-memory `Store` (15 dicts), 71-entry error->HTTP map, `ApiError`/`err`, envelope + pagination, auth/RBAC, `v_*` validators, eager `touch()`/`setf()` version tracking, `Decimal` ROUND_HALF_UP helpers |
| `domain.py` | 558 | lookups, derived aggregates (fund balance, unpaid penalties, outstanding/encumbered recovery, QI active count), coverage/bond interval helpers, `compute_posture`, suspend/revoke/reactivate cascades, all 15 serializers |
| `calc.py` | 195 | statutory constants + 8 pure calculations (credited experience, bond continuity gap, renewal fee, citation civil penalty, sanction points/tier, recovery estimate/final award/pro-rata) |
| `routes_reference.py` | 239 | 13 endpoints (clock, classifications, fund accounts, licensees, QIs, exam results, consumers) |
| `routes_applications.py` | 348 | 7 endpoints (create/submit/cure/withdraw/decision/reads) incl. 3-strike deficiency rule and 4-hop APPROVED licence-minting cascade |
| `routes_licenses.py` | 263 | 7 endpoints (reads, CE banking, renew, reinstate, recovery repayments, compliance sweep) |
| `routes_coverage.py` | 300 | 9 endpoints (coverage filing/verification/cancel, qualifier assignments/withdraw, reads) |
| `routes_complaints.py` | 219 | 7 endpoints (intake, screen, mediation outcome, remand, withdraw, reads) |
| `routes_enforcement.py` | 331 | 10 endpoints (investigations create/close, citations issue/appeal/comply/finalize, reads) |
| `routes_hearings.py` | 224 | 4 endpoints (calendar, decide, reads) incl. sanction ladder |
| `routes_fund.py` | 223 | 5 endpoints (file, adjudicate, pay, reads) |
| `app.py` | 66 | blueprint registration, per-request tx begin, error handlers, `0.0.0.0:$PORT` (default 10000) |
| `start.sh` | 10 | guarded flask install then `exec python3 app.py` (chmod +x) |
| `requirements.txt` | 1 | `flask>=2.0` |

3515 lines total. `python3 -m py_compile *.py` -> COMPILE_OK on all 12 modules. `__pycache__` removed.

**Endpoint coverage: 62/62.** Programmatic diff of the implementation's route decorators against `SCAFFOLD.yaml`'s `endpoints` list: `missing from impl: []`, `extra in impl: []`.

## Smoke test: PASSED (two runs, server launched via `bash start.sh` on port 18795)

Run 1 (licensing lifecycle): unauthenticated request -> `ERR_UNAUTHENTICATED` 401 in the error envelope; bad role -> `ERR_ROLE_NOT_PERMITTED`; clock defaults to `2026-08-01T00:00:00.000Z`; reference data created; exam result computed `expires_on = taken_on + 48 months`; application SUBMITTED -> APPROVED minted `CSLB-100001` (`NON_COMPLIANT` at birth, `expires_on 2028-08-01`); bond verification lifted posture to `CONDITIONAL` and licence `version` to 2; **timely renewal returned `renewal_fee_cents: 71500`, exactly the PRD's worked figure**, with `expires_on 2030-08-01` anchored on the old expiry, `renewal_count: 1`, `ce_hours_completed: 0`. List envelopes carried `limit/offset/total_count/has_more`.

Run 2 (enforcement + fund): complaint screened ACCEPTED -> `MEDIATION` with round 1 and `mediation_deadline 2028-08-31`; failed mediation -> `INVESTIGATION`; investigation closed SUBSTANTIATED; citation issued with `civil_penalty_cents 375000` / `appeal_deadline 2028-08-16`; appeal -> hearing calendared; deciding before `scheduled_start_utc` correctly returned `ERR_HEARING_NOT_CONVENED`, then after advancing the clock the AFFIRM recalculated the penalty with the mitigation credit and produced `sanction_points 4` -> `PROBATION`; fund claim awarded 900000 (claimed 1200000 less the 300000 settlement), paid pro-rata to exhaust the 900000 balance, which suspended the licence with `suspension_reason RECOVERY_FUND_PAYOUT`; the OCC-guarded repayment of 900000 flipped the claim to REIMBURSED, drove `outstanding_recovery_repayment_cents` to 0 and auto-reactivated the licence to ACTIVE. Both `expected_license_version` and `expected_fund_account_version` tokens were accepted at the live version and drive `ERR_STALE_*` otherwise.

Storage is in-memory dicts only — no SQLite, no disk JSON, no `/tmp` cache, and zero seeded rows (both grep-verified and observably true: every entity above came from an API call).

## Step 7: Iterate tests + fixes to green — 2026-09-04

Two parallel 8-round stability sweeps (`--isolation per-test-server`, 159 tests, `setsid nohup`, diagnosed only from per-round `results.$i.json`).

**Iteration 1** — all 8 rounds identical: 151/159 passed, 8 failed. Failure set was byte-identical across rounds (no flakiness; ~297s/round).

- `test_10_*` (all 7 tests) — every one died in setup with `ERR_CONTRACT_PREDATES_LICENSE` (422). Both fixture helpers in that module (`_paid_out_licence_owing_the_fund`, `_slot_released_by_a_payout`) mint the licence at the default clock `2026-08-01` (so `issued_on = 2026-08-01`) and then file a complaint with `contract_date="2026-02-05"`. PRD §3.7: "the `contract_date` must be on or after that licence's `issued_on` ... a contract signed before the licence issued draws `ERR_CONTRACT_PREDATES_LICENSE`." The implementation was correct; the fixture violated the PRD precondition (STEP 2 test bug). Fixed the fixtures to `contract_date="2026-08-05"` / `work_completed_on="2026-08-20"`. PRD couples nothing between `judgment_entered_on` and `contract_date`, so the 90-day ripening (`2026-05-01` + 90d vs. the `2026-09-01` adjudication clock) and the 48-month SOL both still hold, and every award/balance figure the tests assert is unchanged.
- `test_24::test_a_second_remand_hits_the_two_round_ceiling` — asserted `expected_status=422` for `ERR_MEDIATION_ROUNDS_EXHAUSTED`, but PRD §5's catalogue lists that identifier at **409**, which is what the server returned. Assertion mis-translation in `test_suite/`; corrected to 409. (The sibling `expected_status=422` in the same file, for `ERR_HEARING_NOT_CONVENED`, is right per §5 and was left alone.)

Both fixes were confirmed on a 13-test targeted subset run before the re-sweep.

**Iteration 2** — clean: all 8 parallel rounds **159/159 passed**, 0 failed, 0 errors (~286s/round).

Zero tests deleted (every failing test's rule was verbatim in PRD and uniquely derivable). Zero changes to `test_helpers/`. Zero changes to `workspace/implementation/` — the implementation was correct on both counts and no PRD-required check was weakened.

## Step 7 (orchestrator record): Run tests and iterate — 2026-09-04T11:49:21.991Z

Green. Storage confirmed in-memory only (no seeding, no persistence).

## Summary

**Iterations run: 2.**

Iteration 1 (8 parallel rounds, all completed): **151/159** in every round, with a byte-identical failure set across all 8 — no flakiness, two real defects, both in the test artifact.

Iteration 2 (8 parallel rounds): **159/159 passed, 0 failed, 0 errors in all 8 rounds.** ~286s/round.

**Tests deleted: none.** Every failing test's rule was verbatim in PRD and uniquely derivable, so no PRD-silence deletion applied.

**Fixes applied to `test_helpers/`: none.** (The upstream fixture bug lived in a module-local helper inside `test_suite/`, not in the shared helpers.)

**Fixes applied to `test_suite/`:**
- `test_suite/test_10_recovery_fund_conservation.py` — the two module-local fixture builders `_paid_out_licence_owing_the_fund` (line ~65) and `_slot_released_by_a_payout` (line ~244) minted the licence at the default clock `2026-08-01` (so `issued_on = 2026-08-01`) then filed a complaint with `contract_date="2026-02-05"`. PRD §3.7 requires "the `contract_date` must be on or after that licence's `issued_on` … a contract signed before the licence issued draws `ERR_CONTRACT_PREDATES_LICENSE`" — so the PRD-faithful implementation correctly rejected the setup with 422, killing all 7 tests in the module. Changed to `contract_date="2026-08-05"` / `work_completed_on="2026-08-20"`. PRD couples nothing between `judgment_entered_on` and `contract_date`, so the 90-day judgment ripening and the 48-month statute of limitations still hold and every award/balance figure asserted is unchanged.
- `test_suite/test_24_complaint_mediation_cycle_and_hearing_gates.py::test_a_second_remand_hits_the_two_round_ceiling` — asserted `expected_status=422` for `ERR_MEDIATION_ROUNDS_EXHAUSTED`, but PRD §5's error catalogue lists that identifier at **409**, which is exactly what the server returned. Corrected the expected status to 409 (an assertion mis-translation; the exact `error_id` check was preserved, not downgraded). The sibling `expected_status=422` in the same file for `ERR_HEARING_NOT_CONVENED` is correct per §5 and was left untouched.

**Fixes applied to `implementation/`: none.** Both defects were test-side; no PRD-required implementation check was removed or weakened, and no endpoint, field, or side effect was added.

The 8 per-round `results.$i.json` files from the clean sweep are retained under `workspace/implementation/`; `__pycache__`/`.pytest_cache` cleaned and no stray `test_suite`/`test_helpers` under `workspace/`.

**Orchestrator verification of sweep artifacts:** independently parsed all 8 `workspace/implementation/results.$i.json` (each ~49.7 KB, all written 11:43) — every round reports `total 159, passed 159, failed 0, errors 0, skipped 0`. The clean sweep is real, not merely claimed.

**Step 8 gating decision:** the skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes. Step 7 applied 2 `test_suite/` fixes, so Step 8 runs. Note that with 0 `implementation/` fixes a byte-identical `PRD_FINALIZED.md` is a legitimate outcome here: both Step 7 defects were test-side, so neither necessarily implies a PRD silence to patch.

## Step 8: Finalize PRD — 2026-09-04T11:52:00.000Z

## Result

`workspace/PRD_FINALIZED.md` created as a **byte-identical** copy of `PRD.md` (md5 `1c2d3c14116c2f550dac171b32e699dc` on both).

- PRD.md: 491 lines; PRD_FINALIZED.md: 491 lines; delta **0 lines (0.0%)**.
- Changes: **none.** Step 7 applied 0 `implementation/` fixes and deleted 0 tests; both defects were test-artifact bugs whose governing rules are already stated verbatim and uniquely in `PRD.md`, and the implementation matches that prose exactly.

## Candidate-by-candidate investigation (mandatory pre-edit search, run even though it ended in no edit)

**Candidate 1 — `ERR_MEDIATION_ROUNDS_EXHAUSTED` status (test_24 fix)**
- (a) Subject: the HTTP status carried by `ERR_MEDIATION_ROUNDS_EXHAUSTED`, and the remand round/citation guards that raise it.
- (b) Paths enumerated/read: `implementation/core.py:90` (`"ERR_MEDIATION_ROUNDS_EXHAUSTED": 409` in the single central status map — the only place any error->status mapping lives), `implementation/routes_complaints.py:177-204` (`remand_complaint`: both raise sites, lines 189 and 194), `implementation/calc.py:28` (`MAX_MEDIATION_ROUNDS = 2`), plus a repo-wide grep for the identifier (no other emitters). PRD side: §3.7 para "Remanding" (line 284, states the two conditions and the identifier but no status) and §5 (line 455, `409`).
- (c) Wording adjustment: none needed. §5 already pins 409, §3.7's prose is silent on status and therefore not in conflict, and the server returns 409. The test's `expected_status=422` was a pure assertion mis-translation — no PRD silence, no mismatch. (Both impl raise sites use the same identifier, so their check order is unobservable and needs no PRD pinning either.)

**Candidate 2 — `contract_date` vs `issued_on` ordering (test_10 fixture fix)**
- (a) Subject: the licensure-precedence gate at complaint screening, its boundary inclusivity, its applicability condition, and its position in the gate order.
- (b) Paths enumerated/read: `implementation/routes_complaints.py:121-123` (the only `ERR_CONTRACT_PREDATES_LICENSE` raise: fires iff `license_id` resolves, using strict `<` so `contract_date == issued_on` passes), the surrounding gate sequence at `routes_complaints.py:114-127` (statute of limitations -> predates -> jurisdictional minimum) and the fork at `128-146`; `routes_complaints.py:36-74` (`create_complaint` — intake stores `contract_date` and performs *no* such check, so the rule is screening-only); `implementation/core.py:110` (status 422); `implementation/calc.py:28-33` (`STATUTE_OF_LIMITATIONS_MONTHS=48`, `MIN_JURISDICTIONAL_LOSS_CENTS=50000`, `MEDIATION_WINDOW_DAYS=30`, `JUDGMENT_RIPENING_DAYS=90`); grep for any coupling between `judgment_entered_on` and `contract_date` (none exists anywhere in `implementation/`). PRD side: §3.7 line 274 states the gate, its order, its "on or after" boundary, its licence-named precondition and the identifier verbatim; §5 line 475 pins 422.
- (c) Wording adjustment: none needed. Impl and PRD agree on identifier, status, boundary (equality passes), applicability (only when a licence is named), and ordering. The failing setup was a fixture that filed `contract_date=2026-02-05` against a licence issued `2026-08-01`; Step 7 correctly moved the fixture dates instead of touching behavior. The absence of any `judgment_entered_on` <-> `contract_date` coupling in the impl matches the PRD's silence on such a coupling, so asserting anything about it would have manufactured a new claim.

No other subject in `<step_7_diff>` exists (0 impl fixes, 0 test deletions, 0 `test_helpers/` fixes), so no further edits were in scope.

**Orchestrator note:** the byte-identical result is accepted as legitimate for Step 8 specifically because Step 7 recorded 0 `implementation/` fixes — there was no impl-chosen behavior to back-fill into the PRD. Step 9, by contrast, performs a full impl-vs-PRD scan and is expected to produce a non-identical `PRD_COMPLETED.md`; it will be run as three sequential module-partitioned passes over one shared file so that no pass hits the output cap.

## Step 9: Complete PRD — 2026-09-04T12:16:28.874Z

Run as three sequential module-partitioned passes over one shared `workspace/PRD_COMPLETED.md` (pass 1 owned the `cp`; passes 2 and 3 edited in place and were explicitly forbidden to re-copy). Every change was a targeted `Edit`, never a whole-file `Write`, so no pass could truncate the others' work.

### Pass 1 — `core.py`, `app.py`, `calc.py`, `domain.py`

`cp PRD_FINALIZED.md PRD_COMPLETED.md` then 21 in-paragraph edits on 19 lines. 118,172 chars (+5,808). **19 ambiguity-pins, 2 mismatch-revisions.**

- §2.1 — revise — ambiguity — whitespace-only `X-User-ID`/`X-User-Role` also draws `ERR_UNAUTHENTICATED` — core.py:308
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars — core.py:245,250
- §2.2 — insert — ambiguity — `api_request_timestamp` read from the logical clock, sub-ms truncated not rounded — core.py:39,251
- §2.2 — insert — ambiguity — unset fields always present as JSON `null`, never omitted (all 15 serializers use `.get()`) — domain.py:276-558
- §2.3 — insert — ambiguity — `created_at` ties broken by server insertion order — core.py:492
- §2.3 — insert — ambiguity — `total_count` pre-window; `has_more` = `offset + len(page) < total`; filters are exact string equality, no-match yields empty list, unknown query params ignored — core.py:266-275,496-509
- §2.4 — revise — ambiguity — `version` starts at 1, bumps at most once per request however many cascade hops, no bump on a no-op write, and a row created by the same request stays at 1 — core.py:204-239
- §2.4 — insert — ambiguity — date must be exactly `YYYY-MM-DD`; instants accept `Z` or numeric offset and are normalised to UTC, naive read as UTC; month arithmetic clamps to the target month's last day, day arithmetic is plain addition — core.py:320-338,522-531
- §2.5 — revise — **mismatch** — the enumerated flooring sites omitted the renewal-fee CE-shortfall whole-hour floor; added it — calc.py:97
- §2.5 — insert — ambiguity — booleans never accepted for int/number and vice versa; `ownership_pct` / `ce_hours_completed` emitted as ints when whole — core.py:382,401,534-538
- §2.6 — insert — ambiguity — hearing recency is by `decided_at` over `DECIDED` hearings, ties to the later-created row; a vacatur's null tier defeats probation — domain.py:183-194
- §2.8 — insert — ambiguity — cascade version/`updated_at` restamp happens once per row per request and not at all on a value-preserving hop — core.py:204-226
- §2.8 — insert — ambiguity — a `SUSPENDED_BY_LICENSE` designation whose window has closed stays there on reactivation, with no count raise and no qualifier restamp — domain.py:228-239
- §2.8 — insert — ambiguity — revocation of a `SUSPENDED_BY_LICENSE` designation does not restamp its qualifying individual — domain.py:251-259
- §2.11 — insert — ambiguity — JSON `null` treated as omission (required->missing, optional->default); empty/absent body reads as `{}`; non-object or unparseable JSON is itself rejected — core.py:341-361
- §3.3 — insert — ambiguity — `license_number` is `CSLB-` + six digits counting from `CSLB-100001` — core.py:175-177
- §3.5 — insert — ambiguity — a cancelled bond whose `cancellation_date` equals its `effective_date` contributes no span — calc.py:65
- §3.5 — insert — ambiguity — a continuity window whose end precedes its start measures zero days — calc.py:77-78
- §3.6 — insert — ambiguity — fractional CE shortfall rounded down to whole hours (3.5 -> 3) — calc.py:97
- §3.8 — revise — **mismatch** — PRD said appeal grounds go "in the citation's audit trail"; impl stores and exposes a citation field `appeal_grounds` — domain.py:507
- §3.9 — insert — ambiguity — `recovery_paid_to_date_cents` and `outstanding_recovery_repayment_cents` are derived sums over `PAID`/`REIMBURSED` claims, recomputed on every read — domain.py:69-82

Pass 1 deferred one item to pass 3: §3.9's "keeps its earlier `suspension_reason`", since `domain.suspend_license` sets it unconditionally and any guard had to live in a route module.

### Pass 2 — `routes_reference.py`, `routes_applications.py`, `routes_licenses.py`, `routes_coverage.py`

118,172 -> 123,662 chars (+5,490), 0 new lines. **18 ambiguity-pins, 5 mismatch-revisions.**

- §2.4 — insert — ambiguity — clock endpoint enforces no auth/role at all, answers 200 echoing the normalised instant as `current_utc`, missing/unparseable -> `ERR_INVALID_REQUEST` — routes_reference.py:38-43
- §4 table (`/_clock/set_current_utc` row) — revise — **mismatch** — role cell said `BoardAdmin`; impl calls no `require_auth`, so any caller reaches it — routes_reference.py:39
- §3.1 — insert — ambiguity — bad-length or duplicate `code`, and negative `min_experience_months`/`required_ce_hours`, all draw `ERR_INVALID_REQUEST` — routes_reference.py:52,58,61,69-71
- §3.1 — insert — ambiguity — duplicate `fiscal_year` draws `ERR_INVALID_REQUEST` — routes_reference.py:105-107
- §3.2 — insert — ambiguity — `trade_code` stored as supplied, never resolved against the classification table — routes_reference.py:180-185,198
- §3.2 — revise — **mismatch** — PRD claimed a "two-letter" `mailing_state`; impl validates only non-empty string, and no e-mail shape check anywhere — routes_reference.py:224,134
- §3.3 (filing) — revise — **mismatch** — predecessor coupling is tested **before** the duplicate-application gate, and body FKs resolve in declaration order (`licensee_id` -> `classification_id` -> `qualifying_individual_id` -> `predecessor_license_id`) — routes_applications.py:126-140
- §3.3 (approval) — insert — ambiguity — the decision response carries the updated **application**, not the minted licence — routes_applications.py:334
- §3.3 (cure) — insert — ambiguity — cure never clears `deficiency_reason`, and replacements plus their `version` bump persist on a cure that then fails an eligibility gate — routes_applications.py:228-241
- §4 preamble — revise — **mismatch** — "endpoints that bring a new resource into existence answer 201" contradicted the approval path; decision answers 200 with the application although it mints a licence — routes_applications.py:334
- §3.6 (CE banking) — insert — ambiguity — `completed_on`/`provider_name` required, validated then discarded; no credit row persisted; licence is the response — routes_licenses.py:64-83
- §3.6 (CE banking) — insert — ambiguity — licence-state test precedes both hour constraints, `REVOKED` -> `ERR_LICENSE_STATE_INVALID` — routes_licenses.py:70-79
- §3.6 (renewal gate 2) — insert — ambiguity — the posture gate reads the stored `compliance_posture`, not a fresh recomputation — routes_licenses.py:102
- §3.6 (renewal fee) — revise — ambiguity — `renewal_fee_cents` is one extra field carried alongside the licence's fields in `data` — routes_licenses.py:130-132
- §3.6 (reinstatement) — insert — ambiguity — `issued_on`, `expires_on`, `last_renewed_on`, `renewal_count` untouched — routes_licenses.py:157-161
- §3.5 (sweep) — insert — ambiguity — `data` is only the four counters; postures restamped only for licences the sweep itself touched; the three passes run in strict sequence so a just-`EXPIRED` licence is never also suspended — routes_licenses.py:224-263
- §3.9 (repayment) — insert — ambiguity — `EXPIRED`, and `ACTIVE` with nothing outstanding, also report `ERR_LICENSE_STATE_INVALID`, checked after the stale-version guard and before the amount — routes_licenses.py:179-189
- §3.9 (repayment) — insert — ambiguity — only `PAID` claims absorb; the credited claims, their appropriation, the licensee and the licence are each restamped/version-bumped once — routes_licenses.py:191-216
- §3.5 (filing) — insert — ambiguity — `REVOKED` filing draws `ERR_LICENSE_STATE_INVALID`; the date-ordering check precedes licence existence — routes_coverage.py:49-54
- §3.5 (cancellation) — insert — ambiguity — early `cancellation_date` is `ERR_INVALID_REQUEST` and fires *before* the `VERIFIED` state test — routes_coverage.py:143-147
- §3.5 (cancellation) — revise — **mismatch** — suspension trigger is "cancelled record was a `BOND` + no live bond now + licence `ACTIVE`", not "was the only bond covering the clock date"; GL/WC cancellation never suspends — routes_coverage.py:158-161
- §3.4 (designation) — insert — ambiguity — a designation on a `SUSPENDED`/`EXPIRED` licence is still created `ACTIVE` and raises the count — routes_coverage.py:203-236
- §3.4 (withdrawal) — insert — ambiguity — `withdrawn_on` vs `effective_from` is an `ERR_INVALID_REQUEST` evaluated *before* the `ACTIVE` state test — routes_coverage.py:282-286

### Pass 3 — `routes_complaints.py`, `routes_enforcement.py`, `routes_hearings.py`, `routes_fund.py`

123,662 -> 133,752 chars (+10,090), 0 new lines. **23 ambiguity-pins, 4 mismatch-revisions.**

- §3.7 — insert — ambiguity — missing-both-parties is `ERR_INVALID_REQUEST` in the schema band before either FK resolves; `consumer_id` resolved before `license_id`; both subject fields storable together; no floor on `alleged_loss_cents` at intake; `mediation_deadline`/`dismissal_reason`/`remand_reason` start null — routes_complaints.py:47,51-53,66-71
- §3.7 — insert — ambiguity — a `rejection_reason` sent with an `ACCEPTED` finding is schema-legal and then ignored — routes_complaints.py:99,108-110
- §3.7 — insert — ambiguity — `SETTLED` leaves `mediation_deadline` standing; only `FAILED` clears it — routes_complaints.py:165-172
- §3.7 — insert — ambiguity — neither mediation outcome moves `mediation_round_count` — routes_complaints.py:165-173
- §3.7 — insert — ambiguity — withdrawal takes no body; ownership test fires after existence and **before** the state test — routes_complaints.py:210-214
- §3.8 — insert — ambiguity — parent-complaint state test beats all three `ERR_INVESTIGATION_ORIGIN_MISMATCH` tests; `subject_business_name` may accompany `subject_license_id`; `finding`/`finding_severity`/`evidence_summary`/`closed_on` start null — routes_enforcement.py:89-102,111-116
- §3.8 — insert — ambiguity — `OPEN`-state test precedes the assigned-investigator test; a `finding_severity` on an `UNSUBSTANTIATED` finding is accepted then discarded — routes_enforcement.py:150-164
- §3.8 — insert — ambiguity — `correction_due_date` is unconstrained relative to the clock — routes_enforcement.py:187
- §3.8 — insert — ambiguity — `UNLICENSED` citations always carry priors of 0; no cap on citations per substantiated case, and the complaint transition is guarded on `INVESTIGATION` — routes_enforcement.py:36-38,234-238
- §3.8 — insert — ambiguity — citation ownership test position; an `UNLICENSED` citation is appealable/compliable by nobody (`ERR_NOT_RESOURCE_OWNER`) — routes_enforcement.py:55-60,267,310
- §3.8 — insert — ambiguity — finalize carries no body and no ownership test; licensee restamp and posture recompute skipped when there is no licence — routes_enforcement.py:282,293-298
- §3.8 — insert — ambiguity — hearing created with all six decision fields null; the two instants stored/echoed verbatim while comparisons use UTC-normalised values — routes_hearings.py:77-86
- §2.4 — revise — **mismatch** — PRD claimed instants are "normalised to UTC before it is **stored** or compared"; impl stores the raw request string. Narrowed to comparison-only, with server-stamped instants canonical and client hearing instants verbatim — routes_hearings.py:77-78
- §3.8 — insert — ambiguity — `ERR_PENALTY_EXCEEDS_STATUTORY_MAX` also covers the missing and forbidden cases; `modified_penalty_cents` of 0 is valid — routes_hearings.py:151-162
- §3.8 — insert — ambiguity — `AFFIRM` restamps the citation's `prior_final_citation_count`; `correction_verified_on` stamped whether or not it earned credit — routes_hearings.py:181-187
- §3.8 — insert — ambiguity — `MODIFY` keeps the issuance-time priors and ignores `correction_verified_on` — routes_hearings.py:191-194
- §3.8 — insert — ambiguity — `VACATE` still recomputes `compliance_posture` — routes_hearings.py:221-222
- §3.8 — revise — **mismatch** — complaint-follows-disposition was stated unconditionally; impl guards on the complaint still being `CITATION_ISSUED` — routes_hearings.py:205-207
- §3.8 — insert — ambiguity — points/tier are stamped even on an `UNLICENSED` citation, where no licence is touched — routes_hearings.py:110-111,213-220
- §3.8 — revise — **mismatch** — PRD said a disciplinary suspension "likewise cascades its `ACTIVE` designations"; impl cascades only on `ACTIVE -> SUSPENDED`, so an `EXPIRED` licence's designations stand, and a tier on an already-`SUSPENDED` licence is a full no-op — routes_hearings.py:116-120 + domain.py:243-248
- §3.9 — insert — ambiguity — claim filing has no ownership test and `consumer_id` comes from the complaint; `fund_account_id` resolved before `complaint_id` — routes_fund.py:50-51,82
- §3.9 — insert — ambiguity — `awarded_amount_cents` is null (not zero) until adjudication; `denial_reason`/`adjudicated_on`/`paid_on` null — routes_fund.py:92-98
- §3.9 — insert — ambiguity — an explicit `DENY` short-circuits past both the basis and ripening gates — routes_fund.py:133-139
- §3.9 — insert — ambiguity — `denial_reason` stays optional on an explicit `DENY`; `APPROVE` version-bumps the licence on both landing states, `DENY` bumps only the claim, neither touches the licensee — routes_fund.py:125,133-139,175-176
- §3.9 — insert — ambiguity — a cohort member whose floored share is 0 still moves to `PAID`; the cohort ignores `fund_account_id`, so each share is charged against its own appropriation — routes_fund.py:201-212 + domain.py:93-101
- §3.9 — revise — **mismatch (the deferred item)** — resolved below — routes_fund.py:216-220
- §3.9 — insert — ambiguity — the disbursement response carries only the target claim — routes_fund.py:223

**Resolution of pass 1's deferred §3.9 `suspension_reason` question.** The guard does exist, in `routes_fund.py:217`: `domain.suspend_license` is called only inside `if lic["status"] == "ACTIVE":`, so its unconditional `setf(lic, "suspension_reason", reason)` is never reached for a non-`ACTIVE` licence. The PRD's claim was true but incomplete, so it was widened: an already-`SUSPENDED` licence keeps both its earlier `suspension_reason` and its earlier `suspension_until`, and an `EXPIRED` or `REVOKED` licence is not moved to `SUSPENDED` at all — the payout debt surfaces only via the derived figures and the posture. Also pinned that the posture recompute (routes_fund.py:219) runs regardless of status, and that the fourth hop's designation cascade rides on the same `ACTIVE -> SUSPENDED` transition (via `was_active`), so where hop three does nothing hop four does nothing either. The parallel guard at `routes_hearings.py:118` produced the matching §3.8 revision.

### Step 9 totals and orchestrator verification

- `PRD_FINALIZED.md` 491 lines / 112,364 chars -> `PRD_COMPLETED.md` 491 lines / **133,752 chars** (**+21,388 chars, +19.0%**; 0 new lines, 0 new sections).
- **60 ambiguity-pins, 11 mismatch-revisions** across the three passes (71 edits total).
- md5 confirms `PRD_COMPLETED.md` (`c9f2158b...`) is NOT byte-identical to `PRD_FINALIZED.md`/`PRD.md` (`1c2d3c14...`), so the scan genuinely ran in all three passes.
- All 5 top-level sections still present; the file still ends on the complete final `ERR_CLAIM_EXCEEDS_ALLEGED_LOSS` row of §5.
- Cross-pass integrity spot-checked: pass 1's `CSLB-100001` sentence and `appeal_grounds` revision, and pass 2's unauthenticated-clock §4 row, are all still present after pass 3.
- Every file under `workspace/implementation/` still carries its pre-sweep mtime (10:39–10:52, against the green sweep at 11:43), confirming Step 9 was documentation-only and the 8/8 × 159/159 result stands.

**PIPELINE COMPLETE** — Step 9 has written `workspace/PRD_COMPLETED.md`.
