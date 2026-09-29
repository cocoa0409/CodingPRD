# Worklog — task_2692_payroll_tax_amendment_wage_statement_correction

## Step 1: Create task directory — 2026-09-04T07:15:17.610Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2692_payroll_tax_amendment_wage_statement_correction` and its `workspace/` subdirectory. Index 2692 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-04T08:52:51.119Z

All three scaffold artifacts are complete and the linter reports **`VERDICT: clean lint`**.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../task_2692_.../SCAFFOLD.yaml
  Difficulty design:  .../task_2692_.../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../task_2692_.../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    70
  §1.1 entities declared:     14
  §1.8 instances scanned:     24
  §1.9 instances scanned:     56
  Calls scanned (§1.8+§1.9):  936

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2692_payroll_tax_amendment_wage_statement_correction/`)

| File | Lines | Contents |
|---|---|---|
| `SCAFFOLD.yaml` | 3,370 | §1.0–§1.7 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2,320 | §1.8 only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3,236 | §1.9 only |

## SCAFFOLD.yaml counts
14 entities · 13 state machines (4 of them the parallel `CorrectionCase` dimensions) · 2 concurrency rules · 11 calculations · 35 validation rules (priority 1→82) · 70 endpoints · 50 error ids · 7 roles. Profile: `beyond_expert`, ledger_reconciliation + compliance_audit, flat topology, parallel state machines, segregation_of_duties, immediate consistency, layers = dual_variant_calculation / cascading_side_effects / optimistic_concurrency / rate_threshold_triggers / derived_field_reconciliation.

## SCAFFOLD_DIFFICULTY_DESIGN.yaml
**9 rules × 24 instances** (`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`), every rule with ≥2 instances.

## SCAFFOLD_CORNER_DESIGN.yaml
**9 sections / 84 instances — 56 with full `test_recipe`, 28 `excluded_because:` stubs**: entities 11, state_machines 16, calculations 14, validations 9, endpoints 7, errors 12, rbac 7, cross-cutting complexity layers 7, consistency model 1. Names are unique across both design files and every cited `difficulty_instance` resolves.

## Key findings during generation
- **Untriggerable error found and fixed in `SCAFFOLD.yaml`**: `ERR_CASE_HAS_NO_DISCREPANCIES` was attached to `POST /correction-cases/{id}/close`, where reaching `REMEDIATION_PENDING` structurally guarantees ≥1 discrepancy, so the rule was dead. It was retargeted to `POST /amended-returns` (priority 53) and is now exercised from both empty-detection states (`NOT_RUN` and `NO_VARIANCE`).
- All 50 error ids are now triggerable — verified by cross-referencing the catalog against every `error_id` asserted across §1.8 and §1.9.
- **Six lint violations, all in §1.8, fixed**: a missing required `account_number` on an `agency-accounts/{id}/activate` payload; `agency_decision_reference` sent to `amended-returns/{id}/agency-outcome` (that key only exists on the notice `record-outcome` endpoint) in two instances; and three statement-lifecycle calls acting `as: PayrollAnalyst` on endpoints restricted to `[PlatformAdmin, TaxPreparer]`.
- One arithmetic assert was re-derived rather than reused: the PlatformAdmin cross-role instance omits the deposit record, so failure-to-deposit is 0 and the penalty is 46875 (capped FTF 62500 less the 2500 bps voluntary reduction), not the canonical fixture's 65625.
- An actor/role mismatch remains in `SCAFFOLD.yaml` by design choice: `POST /agency-notices/{id}/draft-response` lists roles `[PlatformAdmin, TaxOfficer]` while the state machine names `TaxPreparer` as actor; all recipes act `as: TaxOfficer` so §1.5 remains authoritative.

## Step 3: Copy shared files — 2026-09-04T08:53:00.887Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T09:12:27.847Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — **466 lines, 16,371 words**. Ends cleanly on the last row of the §5 error table (no truncation, no audit footer inside the file).

**Sections emitted**

- `## 1. Introduction` — 3 paragraphs (pain point, reconciliation-ledger-with-compliance-overlay framing, two cross-cutting consequences).
- `## 2. Global Specifications & System-Wide Principles` — 11 domain-derived subsections: 2.1 Identity/RBAC, 2.2 API Response Structure (byte-identical copy of `skills/prd-bench-doc-generator/section-2.2-response-structure.md`, verified), 2.3 Pagination and List Ordering, 2.4 Record Identity/Audit Stamps/Row Versioning, 2.5 Logical Clock and Period Arithmetic, 2.6 Money/Basis Points/Rounding, 2.7 OCC on Parent Rows, 2.8 Segregation of Duties, 2.9 Flat Addressing/Referential Scope/Existence, 2.10 Rejection Precedence, 2.11 Derived Rollups/Cascades/Recomputation.
- `## 3. Business Logic & Workflows` — 9 subsections: 3.1 reference data + registration coverage + payroll evidence, 3.2 case opening + three-way reconciliation, 3.3 discrepancy triage, 3.4 amendment drafting + delta rollup + interest/penalty, 3.5 signature/transmission/agency disposition, 3.6 corrected wage statements + reissue chain, 3.7 wage repayment recovery + collection cascade, 3.8 agency notices + abatement waiver, 3.9 control remediation + closure + exposure ledger.
- `## 4. Endpoint Definitions` — 1 lead paragraph + 70-row, 4-column table.
- `## 5. Error Code Catalogue` — 50-row, 2-column table.

**Coverage confirmation (all machine-checked against SCAFFOLD.yaml)**

- **Endpoints: 70/70.** Method+path set diff against `endpoints[]` is empty in both directions, and every row's Authorized Role(s) cell matches the scaffold's `roles` exactly (0 mismatches).
- **Errors: 50/50** in the §5 table, and all 50 ids also appear in §1–§4 prose (the 4 "missing" hits were compound multi-id validation strings whose components are each present).
- **Validations: 35/35.** Every priority 1–82 is expressed in §2.10's precedence ladder and again at its point of use in §3; every distinct `error_id` appears in prose.
- **Calculations: 11/11**, with every constant value present: emission category order (`TAXABLE_WAGE`/`WITHHOLDING`/`JURISDICTION_ASSIGNMENT`/`DEPOSIT_SHORTFALL`), FTD ladder 200/500/1000 bps on the 0–5 / 6–15 / 16+ day bands, FTF 500 bps-per-month capped at 5 months and 2500 bps, `MIN_PENALTY_CENTS` 5000, `VOLUNTARY_REDUCTION_BPS` 2500, first-time ceiling 5000000, 10000/5000/6000/2000 bps abatement tiers, `DE_MINIMIS_CENTS` 2500, `PRIOR_YEAR_WINDOW_YEARS` 3.
- **State machines: 13/13, all 58 transitions** narrated including both self-loops (case re-reconcile, remediation assign), both compensating cycles (`SIGNED → DRAFT`, `AGENCY_REJECTED → DRAFT`, `VERIFICATION_FAILED → SUBMITTED_FOR_VERIFICATION`, `AGREED → PROPOSED`, `RESOLVED → CATEGORIZED`), all three `VOID` branches, and both five-link cascades. Every state token resolves in the PRD.

**Hard Contracts**

- **Contract 1 (Field-Name Coverage): PASS** — 154 required identifiers (all `entities[].fields[].name`, all endpoint `input` fields, all query params, all 14 path params, both computed-read output shapes); 0 missing from backticked PRD text.
- **Contract 2 (Rule Coverage): PASS** — 35/35 validations, 2/2 concurrency rules, 11/11 calculations, 58/58 transitions, all cascade side-effect chains, `applies_to` scopes and field-level defaults expressed in prose; no pseudocode, no fenced code blocks other than the two canonical §2.2 JSON envelopes, no fuzzy quantifiers.
- **Contract 3 (§3 Path Purity): PASS** — 0 violations: no backticked token between `## 3.` and `## 4.` starts with `/`, is a bare HTTP method, or combines method+path.

Two headings were renamed late to match the skill's structure template exactly (`## 4. Endpoint Definitions`, `## 5. Error Code Catalogue`). Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was read.

**Orchestrator truncation check (per pipeline directive):** `tail -25` confirms PRD.md ends on a complete `| ERR_WAIVER_EXCEEDS_ASSESSMENT | 422 |` table row at a real section boundary; heading scan shows all 5 top-level sections and all 11 §2 + 9 §3 subsections present. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-04T10:43:06.608Z

Generation is complete and verified. Final deliverable:

## Output locations (task root, nothing under `workspace/`)

**`test_helpers/`** — 2382 lines
| file | lines |
|---|---|
| `__init__.py` | 116 |
| `api_client.py` | 454 |
| `api_errors.py` | 150 |
| `assertions.py` | 239 |
| `constants.py` | 214 |
| `factories.py` | 356 |
| `fixtures.py` | 503 |
| `test_users.py` | 99 |
| `types.py` | 251 |

**`test_suite/`** — 5224 lines, 105 tests
| file | lines | tests |
|---|---|---|
| `conftest.py` | 51 | — |
| `test_01_reference_data_and_registration_coverage.py` | 664 | 17 |
| `test_02_reconciliation_and_discrepancy_triage.py` | 318 | 7 |
| `test_03_amendment_interest_and_penalty_arithmetic.py` | 608 | 11 |
| `test_04_amendment_drafting_and_preparation_gates.py` | 426 | 8 |
| `test_05_amendment_signature_and_transmission.py` | 433 | 8 |
| `test_06_amendment_disposition_void_and_exposure.py` | 513 | 10 |
| `test_07_corrected_wage_statements_and_the_reissue_cycle.py` | 603 | 13 |
| `test_08_wage_repayment_recovery_and_its_cascade.py` | 376 | 9 |
| `test_09_agency_notices_and_the_abatement_argument.py` | 372 | 8 |
| `test_10_control_remediation_and_case_closure.py` | 409 | 5 |
| `test_11_access_control_envelope_and_precedence.py` | 451 | 9 |

7606 lines total.

## Design-index coverage

- **Queue A (Difficulty, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` §1.8): 24/24 instances translated, 0 skipped.** 48 `Design: Difficulty/...` tags — every instance carries at least two tests (the multi-level cascade/formula instances are split across a "forward" and a "consequence" test).
- **Queue B (Corner, `SCAFFOLD_CORNER_DESIGN.yaml` §1.9): 56/56 non-stub instances translated, 0 skipped.** 57 `Design: Corner/...` tags across 56 distinct instance names (one instance carries two tests). The 28 instances bearing `excluded_because:` were correctly left untranslated.
- **Skipped-instance list: empty.** Every instance passed the two-condition PRD-first filter — each had verbatim rule-bearing PRD prose to cite and a uniquely-derivable asserted outcome. Three instances needed *reinterpretation* rather than skipping, and the tests assert only what the PRD derives:
  - `amended_return_acceptance_cascade_depth_five` L5 asserts employer `open_exposure_cents == 335625` (the design's `== 0` contradicts PRD §330, which keeps a `REMEDIATION_PENDING` case in the open sum).
  - The `dominant_root_cause_code` tie-break is not derivable from the PRD, so it is asserted as non-null / equal to the cascade-produced value rather than a literal.
  - Recipe user ids that do not exist in the declared identity set (`u_owner_kim`, `u_aud_lin`, `u_off_bree`) were mapped onto the PRD's declared identities; `verified_by_user_id` is asserted against the real acting id.

## Verification evidence

- Mechanical citation/tag audit: **CLEAN** — 105 tests, 105 `Design:` lines, no untagged, dual-tagged, or non-existent-instance tags; every `PRD: "..."` line survives a literal substring match against `workspace/PRD.md`.
- `python3 -m py_compile` clean on all 12 suite modules; all 11 `test_*.py` modules import successfully under `PYTHONPATH=.` (so no missing or renamed helper symbols); AST sweep reports no unused imports.
- `find workspace -name test_helpers -o -name test_suite -o -name conftest.py` returns nothing — no strays inside `workspace/`. `__pycache__` dirs removed.
- Per instruction: `workspace/implementation/` was never read and the tests were **not run**.
- Money fields are emitted as JSON numbers throughout the factories (integer cents), never strings.

## Step 6: Generate implementation — 2026-09-04T10:43:06.608Z

Implementation complete and verified. All work is under `workspace/implementation/`.

## Files created (line counts)

| File | Lines |
|---|---|
| `app.py` | 77 |
| `common.py` | 606 |
| `calc.py` | 539 |
| `serializers.py` | 172 |
| `routes/__init__.py` | 0 |
| `routes/reference.py` | 339 |
| `routes/evidence.py` | 228 |
| `routes/cases.py` | 254 |
| `routes/amendments.py` | 362 |
| `routes/statements.py` | 303 |
| `routes/repayments.py` | 228 |
| `routes/notices.py` | 229 |
| `routes/remediations.py` | 158 |
| `routes/clock.py` | 18 |
| `requirements.txt` | 1 (`flask>=2.0.0`) |
| `start.sh` | 10 |
| **total** | **3524** |

`python3 -m py_compile` on every module → COMPILE_OK. No `__pycache__` left behind.

## Coverage

- **Endpoints: 70 / 70 declared.** Verified programmatically by counting registered Flask rules (`registered endpoints: 70`).
- **Calculations: 11 / 11** — `three_way_variance_detection`, `jurisdiction_wage_apportionment`, `amended_return_delta_rollup`, `amendment_interest_accrual` (both `STATUTORY_DAILY` and `DEPOSIT_WEIGHTED` variants), `amendment_penalty_assessment`, `repayment_recovery_basis`, `statement_box_deltas`, `abatement_penalty_waiver`, `case_exposure_rollup`, `employer_open_exposure_rollup`, `corrected_wage_base_rollup`.
- **State machines: 13 / 13** — AgencyAccount.registration_status; CorrectionCase × 4 parallel dimensions (detection/filing/statement/status); Discrepancy; AmendedReturn; FiledReturn; CorrectedWageStatement; WageRepayment; AgencyNotice × 2 (response/abatement); ControlRemediation.
- Storage is in-memory dicts only, empty on boot (verified: `GET /employers` → `total_count 0` on a fresh process). No seeding, no disk persistence.

## start.sh verification

Fresh boot on `PORT=51999`: reads `$PORT`, binds `0.0.0.0`, runs Flask in the foreground via `exec python3 app.py` (no `&`/nohup inside). `pip install` is guarded by an import probe so 8 concurrent per-test reboots don't contend. Header enforcement confirmed on a cold process: `GET /employers` with no identity headers → 401, `POST /_clock/set_current_utc` with no headers → 200 (the sole exempt endpoint).

## Smoke test results

Three self-written smoke suites over a real HTTP server (high port, single PID killed by port lookup each time; no broad pkill ever used).

- Part 1: 30 PASS / 2 FAIL — both my assertion bugs (expected 422 for SoD which is 403; and a flow that expected the remediation join while the case was still `STMT_PENDING`).
- Part 2: 33 PASS / 6 FAIL — all my script bugs (wrong expected HTTP codes; a recall clears `submitted_at` so cooling-off is trivially satisfied; a reissue attempted from `ACKNOWLEDGED`).
- Part 3 (written this pass): **80 PASS / 0 FAIL**, covering the three `void` branches with the prepare-then-void exposure invariant, SoD-vs-role precedence, `ERR_AUTHORIZATION_LIMIT_EXCEEDED`, the full acceptance 5-link cascade, remediation verify cycle + `ERR_REMEDIATION_NOT_VERIFIED` + case close, reissue-from-`ISSUED` → HTTP 201 with `STMT_ISSUED → STMT_REISSUE_PENDING` and the `REMEDIATION_PENDING → OPEN` reopen, the repayment collection cascade (both counted statements voided, two DRAFT successors, links 4 and 5, employee counts to 0), renegotiate basis switch (`SAME_YEAR_NET` 309400/90600 → `PRIOR_YEAR_GROSS` 400000/30600), `ERR_OVERCOLLECTION`, all abatement branches (de-minimis sweep, halved-then-capped `ABATED_PARTIAL`, `UPHELD`, supplemental round via `request-info`, overdue, duplicate notice number), `ERR_AMENDMENT_SLOT_OCCUPIED`, `ERR_STALE_CASE_VERSION`, `ERR_AMENDMENT_WINDOW_CLOSED`.
- Pinned worked examples reproduced exactly: per-line apportionment 150003; Q1/Q2 statutory due dates; `DEPOSIT_WEIGHTED` **34833** vs `STATUTORY_DAILY` **30000** on the PRD's exact inputs, plus the no-deposit fallback; penalty floor→multiplier→voluntary giving 3750; abatement de-minimis net 2000.

## Two implementation defects found and fixed in this final pass

1. `routes/statements.py` treated `ACKNOWLEDGED` as terminal. The scaffold declares `terminal_states: [VOIDED]` for `CorrectedWageStatement` (the repayment cascade can still void an acknowledged row), so reissuing/acknowledging an `ACKNOWLEDGED` statement now answers `ERR_INVALID_STATE`, not `ERR_ALREADY_TERMINAL`.
2. `issue_statement` moved the case's statement dimension to `STMT_ISSUED` but never attempted the compound `OPEN → REMEDIATION_PENDING` join, so a case whose filing dimension was already `FILING_NOT_REQUIRED`/`FILING_COMPLETE` never reached remediation (and never auto-created its `PROCESS_CONTROL` remediation) when driven from the statement side. It now calls `calc.join_remediation_pending(case)` on that move, matching the CorrectionCase.status trigger "statement_status reaches STMT_ISSUED or STMT_COMPLETE while filing_status IN {FILING_NOT_REQUIRED, FILING_COMPLETE}".

Re-running parts 1 and 2 after both fixes produced no new failures. No smoke servers are left running.

**Orchestrator layout verification:** `test_helpers/` (9 files) and `test_suite/` (12 files) are at the task root; `workspace/` contains only INSTRUCTION.md, PRD.md and implementation/. Stray sweep (`find workspace -name test_helpers -o -name test_suite -o -name conftest.py`) returned nothing.

## Step 7: Run tests and iterate — 2026-09-04T10:58:36.978Z

Loop complete — clean 8-round parallel sweep.

## Summary

**Iterations run:** 2

**Iteration 1** (baseline): all 8 rounds identical — 105/106 passed, 1 deterministic failure (no flakiness, no load-induced connection failures; per-round durations were all ~189s, confirming the rounds were not reaped).

Failing test (union across all 8 rounds, single member):
`test_suite/test_11_access_control_envelope_and_precedence.py::TestPaginationBounds::test_the_inclusive_upper_bound_passes_and_everything_outside_the_band_is_refused` — `KeyError: 'data'`

**Diagnosis:**
- STEP 1a/1b: the rule the test asserts *is* verbatim in PRD §2.2/§2.3 — "A `limit` outside the inclusive range of 1 through 100, or a negative `offset`, or either value supplied as something other than an integer, is rejected with `ERR_INVALID_PAGINATION` and HTTP 400", plus the error envelope's `data` carrying exactly `error_id` and `message`. Uniquely derivable, so the test stays.
- STEP 2: the failure was never in the implementation — the endpoint returned the correct `ERR_INVALID_PAGINATION` / 400 for all three params (`validate_error` passed). The test then indexed the helper's return value as if it were the full envelope. `prd_bench_local_runner.testing.validate_error` returns the *inner* `data` dict (`return error_data`), so `body["data"]` raised `KeyError`. Assertion mis-translation in `test_suite/` → fixed there.

**Tests deleted:** none. No test failed PRD coverage or unique-derivability.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none. No implementation defect was found; the single failure was a test-side helper-contract misuse.

**Fix applied to `test_suite/`:**
- `test_suite/test_11_access_control_envelope_and_precedence.py` — `TestPaginationBounds::test_the_inclusive_upper_bound_passes_and_everything_outside_the_band_is_refused`: renamed the misnamed `body` binding to `error_payload` and asserted `set(error_payload) == {"error_id", "message"}` directly, since `validate_error` already returns the envelope's `data` payload. The assertion is unchanged in strength — it still requires the error payload to carry exactly the two PRD-declared keys; only the (broken) indexing was corrected. Verified this was the sole occurrence of the misuse across `test_suite/`.

**Iteration 2** (post-fix sweep): all 8 parallel rounds **106/106 passed, 0 failed, 0 errors**.

Cleanup: removed `__pycache__` dirs, the eight `results.*.json` files, and `workspace/sweep.log`; `workspace/implementation/` contains only the source files, `requirements.txt`, `routes/` and `start.sh`. No stray `test_suite/`, `test_helpers/` or `conftest.py` under `workspace/`.

### Orchestrator-run independent verification sweep — 2026-09-04T10:58:36.978Z

The Step 7 subagent deleted its `results.*.json` artifacts on exit, which the pipeline output spec requires to be present, so the orchestrator re-ran the full 8-round sweep itself under `setsid nohup` (rounds not reaped; `SWEEP_DONE` observed in sweep.log). Result — every round green, artifacts left in place:

```
results.1.json passed=106 total=106 failed/errors=(0, 0) dur=193.18
results.2.json passed=106 total=106 failed/errors=(0, 0) dur=193.20
results.3.json passed=106 total=106 failed/errors=(0, 0) dur=193.13
results.4.json passed=106 total=106 failed/errors=(0, 0) dur=193.18
results.5.json passed=106 total=106 failed/errors=(0, 0) dur=193.16
results.6.json passed=106 total=106 failed/errors=(0, 0) dur=193.23
results.7.json passed=106 total=106 failed/errors=(0, 0) dur=193.19
results.8.json passed=106 total=106 failed/errors=(0, 0) dur=193.22
ALL_GREEN
```

**Step 8 decision:** Step 7 reported 0 deletions, 0 `test_helpers/` fixes, and 0 `implementation/` fixes, but it DID apply one `test_suite/` fix, so the skill's zero-iteration skip condition is not met and Step 8 runs. The single Step 7 diff item is a pure test-side helper-contract misuse (`validate_error` return shape), not a PRD silence, so Step 8 is expected to find little or nothing to patch — a byte-identical `PRD_FINALIZED.md` would be a legitimate outcome here. Step 9 then performs the full PRD-vs-implementation scan regardless.

## Step 8: Finalize PRD — 2026-09-04T11:00:00.000Z

## Result: PRD_FINALIZED.md written, byte-identical to PRD.md (0 edits)

`workspace/PRD_FINALIZED.md` exists on disk (466 lines, md5 `ff57be7a046b952d1d3e32d39891db9e`, same as PRD.md).

- **Line counts:** PRD.md 466 → PRD_FINALIZED.md 466. **%-delta: 0.00%.**
- **Change bullets:** none.

### Why no edit was warranted

The sole Step 7 diff item (`test_11_access_control_envelope_and_precedence.py::TestPaginationBounds::test_the_inclusive_upper_bound_passes_and_everything_outside_the_band_is_refused`, `KeyError: 'data'`) was a test-side misuse of `prd_bench_local_runner.testing.validate_error`, which already returns the envelope's inner `data` payload. It exposed no PRD silence and no PRD/impl divergence. I verified both halves of the behavior the test exercises against the implementation:

**Pagination band (PRD §2.3 vs `implementation/common.py:376-401`)** — `pagination()` defaults `limit=10` / `offset=0`, rejects non-integer `limit`/`offset` with `ERR_INVALID_PAGINATION`, rejects `limit < 1 or limit > 100`, rejects `offset < 0`. `common.py:45` maps `ERR_INVALID_PAGINATION → 400`. This is exactly PRD §2.3's sentence, already verbatim in the PRD: *"A `limit` outside the inclusive range of 1 through 100, or a negative `offset`, or either value supplied as something other than an integer, is rejected with `ERR_INVALID_PAGINATION` and HTTP 400."* `limit=100` is an inclusive success, as the test's passing first leg confirms.

**Error envelope (PRD §2.2 vs `implementation/common.py:146-153`)** — `error_response()` emits `meta` with only `api_request_id` + `api_request_timestamp`, `response_type: "error"`, and `data` with exactly `error_id` and `message`. Matches §2.2 verbatim.

Nothing to insert or revise; per the instructions I did not manufacture edits, and I did not touch anything outside the diff item's subject.

### Pre-edit search log

Zero edits were committed, so there is no per-edit log. For completeness, the two candidate subjects I investigated and then declined to edit:

1. **Subject: pagination parameter validation and its refusal code.**
   (b) Paths enumerated/read: `implementation/common.py` `pagination()` (376-401), the `ERR_INVALID_PAGINATION → 400` entry in the status map (`common.py:45`), `paginate()` (436-439), `ok_list()` (133-141) for the `meta` window fields, and `sorted_rows()` (430-431). Grepped `ERR_INVALID_PAGINATION` and `pagination(` across `implementation/routes/*.py` to confirm every list endpoint routes through the one shared `pagination()` helper rather than validating locally — it does, so there is no off-Step-7 endpoint exhibiting a different band.
   (c) No wording adjustment: PRD §2.3 already describes this uniquely and consistently with all enumerated paths. Declined to edit.

2. **Subject: the error-response envelope shape.**
   (b) Paths enumerated/read: `implementation/common.py` `error_response()` (146-153), `_base_meta()` (117-122), `fail()` / the error-status map (`common.py:~40-60`), and `ok()`/`ok_list()` as the contrasting success shapes. Confirmed `error_response` is the single construction point for all 4xx bodies, so no route emits a differently-shaped error payload.
   (c) No wording adjustment: PRD §2.2's error-envelope block already matches every enumerated path. Declined to edit.

Note on scope discipline: while reading `common.py` I noticed two behaviors the PRD does not uniquely pin — the `created_at`/`_seq` insertion tiebreak in `sorted_rows()`, and whitespace tolerance in the `str(raw).strip() != str(limit)` integer check. Neither traces to a Step 7 fix, deletion, or test change, so per the hard scope rule I left both unpinned. (Orchestrator note: both are exactly the kind of residual silence Step 9's full scan is responsible for, and they have been flagged to Step 9's pass-1 subagent.)

**Orchestrator adjudication:** a byte-identical `PRD_FINALIZED.md` is the legitimate outcome when Step 7 made 0 implementation fixes — the one Step 7 diff item was a test-side helper-contract misuse, not a PRD silence. Verified on disk: both files md5 `ff57be7a046b952d1d3e32d39891db9e`. Step 9 (full PRD-vs-implementation scan) runs next and is the step that must NOT come back identical.

**Step 9 execution plan:** the implementation is 3,524 lines across 16 files, which is too large for one subagent to scan reliably in a single pass (a single-pass Step 9 characteristically returns a byte-identical file because the scan never actually ran). Step 9 is therefore split into three SEQUENTIAL module-partitioned passes over one shared `PRD_COMPLETED.md`:
- Pass 1 (does the `cp PRD_FINALIZED.md PRD_COMPLETED.md`): `app.py`, `common.py`, `serializers.py`, `routes/clock.py`, `routes/reference.py`, `routes/evidence.py`, `routes/cases.py`
- Pass 2 (must NOT cp): `calc.py`, `routes/amendments.py`
- Pass 3 (must NOT cp): `routes/statements.py`, `routes/repayments.py`, `routes/notices.py`, `routes/remediations.py`

## Step 9: Complete PRD — 2026-09-04T11:32:52.552Z

Run as three SEQUENTIAL module-partitioned passes over one shared `PRD_COMPLETED.md`. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from re-copying and edited the file in place with the Edit tool only.

### Aggregate result

`workspace/PRD_COMPLETED.md` — **468 lines / 145,628 chars**, from source `PRD_FINALIZED.md` at **466 lines / 120,604 chars**. Delta **+2 lines / +25,024 chars (+20.7%)** across **69 diff hunks**. **94 edits total: 69 ambiguity-pins, 25 mismatch-revisions.** Section count unchanged at 28 headings — no new sections; every patch was an in-paragraph insert or revision.

### Pass 1 — `app.py`, `common.py`, `serializers.py`, `routes/clock.py`, `routes/reference.py`, `routes/evidence.py`, `routes/cases.py`

36 edits (28 ambiguity-pins, 8 mismatch-revisions). Owned the `cp`. 466 → 468 lines, 120,604 → 130,419 chars.

Mismatches:
- `§2.9` — revise — scope rule guards **four** creations, not five; categorising a discrepancy is not scope-guarded and never yields `ERR_SCOPE_MISMATCH` — `routes/cases.py:214-234`
- `§3.3` — revise — removed the claim that categorisation can be refused with `ERR_SCOPE_MISMATCH`; the case is read from the row's own `correction_case_id` — `routes/cases.py:223`
- `§2.10` — revise — ownership outranks existence/schema only where scope comes from the addressed row or filter; on creates the body FK must resolve and the body must validate first — `routes/reference.py:306-309`, `routes/cases.py:29-35`
- `§4 /employers` — revise — "legal name fragment or filing status" → exact `fein` / `deposit_schedule` — `routes/reference.py:68`
- `§4 /employees` — revise — "identifier fragment" → `employer_id` / `mailing_state_code` — `routes/reference.py:334-337`
- `§4 /payroll-register-lines` — revise — dropped the nonexistent `posting_status` filter — `routes/evidence.py:76-82`
- `§4 /deposit-records` — revise — "deposit date range" → `clearing_status` — `routes/evidence.py:143-149`
- `§4 /discrepancies` — revise — dropped nonexistent root-cause filter, added `employee_id`/`register_line_id`/`resolved_amended_return_id` — `routes/cases.py:200-207`

Ambiguity pins (28): `created_at` ties break on insertion sequence earliest-first, never by `id` (`common.py:432`); pagination tolerates surrounding whitespace but rejects `+10`/`010`/`10.0`/empty, `limit` validated before `offset` (`common.py:377-401`); filters are exact-equality and unparseable/empty filters match nothing rather than erroring, undeclared params ignored (`common.py:404-448`); whitespace-only headers are `ERR_UNAUTHENTICATED` (`common.py:503-518`); list scoping forces an `employer_id`/`employee_id` filter with `ERR_NOT_RESOURCE_OWNER` on a foreign one, while the discrepancy list narrows silently (`common.py:487-500`); clock setter ignores headers entirely (`routes/clock.py:13-18`); `api_request_id` is `req_` + exactly 20 upper-case alphanumerics (`common.py:100-104`); instant parsing accepts `Z`/offset/zoneless-as-UTC and publishes UTC with 3 fractional digits (`common.py:254-267`); ROUND_HALF_UP away from zero, exact integer arithmetic, zero divisor → 0 (`common.py:217-231`); explicit `null` semantics, booleans never integers, absent body = `{}` (`common.py:281-350`); no-op employer PATCH still bumps `version` (`routes/reference.py:73-83`); `effective_to` year-without-quarter → `ERR_INVALID_REQUEST` while quarter-without-year is silently discarded (`routes/reference.py:188-197`); `account_number` 1–64 (`routes/reference.py:152`); activation gate split and absence of overlap re-check (`routes/reference.py:242-252`); retro back-dating touches no case row (`routes/reference.py:250-267`); closure requires both fields and validates neither ordering nor overlap (`routes/reference.py:271-287`); the case four-part key is not unique (`routes/cases.py:24-57`); reconcile gate order and body ignored (`routes/cases.py:92-97`); frozen-set refusal is `ERR_INVALID_STATE` (`routes/cases.py:99-103`); a re-run never re-derives the three dimensions (`routes/cases.py:108-113`); discrepancy state tested before case state (`routes/cases.py:224-246`); `dismissal_reason` 1–2000 (`routes/cases.py:242`); closure gate split and `closure_note` persisted nowhere (`routes/cases.py:136-140`); exposure-summary returns exactly six fields and writes nothing (`routes/cases.py:157-171`); added missing `jurisdiction_code` and `retroactive` filters (`routes/reference.py:136-237`); out-of-catalogue `ERR_ROUTE_NOT_FOUND` 404 / `ERR_METHOD_NOT_ALLOWED` 405 in the standard envelope, trailing slash equivalent (`app.py:38-54`); outside the four guarded creations only existence is checked, never cross-row agreement (`routes/evidence.py:39-47`).

### Pass 2 — `calc.py`, `routes/amendments.py`

24 edits (16 ambiguity-pins, 8 mismatch-revisions). No `cp`. 130,419 → 136,210 chars, line count held at 468.

- §2.1 — revise — mismatch — the amended-return list is also unfiltered and silently narrowed for `EmployerRep` — `routes/amendments.py:110`
- §2.10 — revise — mismatch — terminal test outranks `ERR_AMENDED_RETURN_NOT_SIGNED` on transmission — `routes/amendments.py:237`
- §2.11 — revise — mismatch — a recomputation landing on unchanged values touches neither `version` nor `updated_at`; all five case rollups / all three employer counters always recomputed together — `calc.py:171-228` (resolves the `sync_case` conditional-bump lead globally, also covering `sync_employer`/`sync_employee`)
- §3.2 — revise — mismatch — "exactly one filed return must exist" is not enforced; the earliest-created `FILED`/`AMENDED` row is read and supplies `original_due_date` — `calc.py:62-64`
- §3.2 — insert — ambiguity — freshly emitted discrepancies carry null `category`, `root_cause_code`, `dismissal_reason` and both resolution fields — `calc.py:284-298`
- §3.3 — insert — ambiguity — dominant-root-cause tie beyond equal `created_at` broken by insertion order — `calc.py:138`
- §3.4 — insert — ambiguity — draft resolves both body FKs before schema validation, case first — `routes/amendments.py:44-47`
- §3.4 — revise — ambiguity — "a state that permits preparation" pinned to `DRAFT`/`SIGNED`/`AGENCY_REJECTED`, `PREPARED` → `ERR_INVALID_STATE`; the three remaining gates guard only `DRAFT → PREPARED` — `routes/amendments.py:139-160`
- §3.4 — insert — ambiguity — a `JURISDICTION_ASSIGNMENT` row with null/unresolvable `register_line_id` contributes 0 — `calc.py:314-318`
- §3.4 — insert — ambiguity — the `DEPOSIT_WEIGHTED` no-obligation fallback still records `interest_variant` as `DEPOSIT_WEIGHTED` — `calc.py:347-349`
- §3.4 — insert — ambiguity — a negative gross penalty passes the 5000-cent floor unchanged — `calc.py:388-389`
- §3.4 — insert — ambiguity — `SIGNED → DRAFT` recall retains six computed fields and leaves `filing_status` at `FILING_IN_PROGRESS` — `routes/amendments.py:141-151`
- §3.4 — insert — ambiguity — `AGENCY_REJECTED → DRAFT` clears nothing else and recomputes no rollup — `routes/amendments.py:153-159`
- §3.5 — revise — mismatch — transmission on `ACCEPTED`/`VOID` answers `ERR_ALREADY_TERMINAL` — `routes/amendments.py:237-240`
- §3.5 — revise — ambiguity — cooling-off "most recent" = latest `submitted_at`, ties by insertion order — `routes/amendments.py:265`
- §3.5 — revise — ambiguity — `rejection_reason` 1–2000, validated then ignored on the accepting branch — `routes/amendments.py:283-286`
- §3.5 — insert — ambiguity — rejection recomputes nothing, so stored `total_exposure_cents` keeps the rejected amendment while the recomputing read already excludes it — `routes/amendments.py:292-296`
- §3.5 — revise — mismatch — acceptance moves **every** `FILED` return on the case scope to `AMENDED` — `routes/amendments.py:302-305`
- §3.5 — revise — ambiguity — `void_reason` 1–2000; `SIGNED`/`SUBMITTED` voids answer `ERR_INVALID_STATE` — `routes/amendments.py:326-330`
- §3.6 — revise — ambiguity — collected-repayment `created_at` descending tie broken by reversed insertion order — `calc.py:436`
- §3.8 — insert — ambiguity — null `abatement_grounds` takes the `UPHELD` stopping route whatever the outcome — `calc.py:468`
- §3.8 — insert — ambiguity — `ABATED_PARTIAL` with no requested waiver amount is not capped — `calc.py:489`
- §3.9 — revise — mismatch — closure *recomputes* `open_remediation_count` rather than decrementing it — `calc.py:196-198`
- §4 — revise — mismatch — amended-return list filters are `correction_case_id`, `supersedes_amended_return_id`, `form_code`, `status`, `interest_variant`; no employer/agency filter — `routes/amendments.py:102-111`

### Pass 3 — `routes/statements.py`, `routes/repayments.py`, `routes/notices.py`, `routes/remediations.py`

34 edits (25 ambiguity-pins, 9 mismatch-revisions). No `cp`. 136,210 → 145,628 chars, line count held at 468.

§3.6 statements: `sequence_no` counts VOIDED rows, FK order case→employee→supersedes, drafting fires no rollup (`statements.py:45-94`); added missing `delivery_channel` list filter (`:115`); prior-year boundary skipped not refused when no return/agency, three issue gates in §2.10 order (`:148-162`); case `version` bump on issue conditional on the dimension moving and issuing against `STMT_NOT_REQUIRED`/`STMT_ISSUED`/`STMT_COMPLETE` is not refused (`:125-177`); **`ACKNOWLEDGED` is not terminal** — only `VOIDED` gives `ERR_ALREADY_TERMINAL` (`:18-20,193`); acknowledge recomputes three rollups but moves nothing (`:197-206`); `undeliverable_reason` 1–2000 (`:215`); `reissue_reason` 1–2000 validated but persisted nowhere, `corrected_mailing_state_code` exactly two uppercase letters and bumps the employee row (`:237-296`); successor inherits `delivery_channel`, re-derives `is_prior_year`, and is exempt from `ERR_NO_REPORTABLE_DELTA`; reissue re-checks neither three-year reach nor repayment settlement (`:242-262`); the 201 body is the successor (`:303`); the `STMT_ISSUED → STMT_REISSUE_PENDING` flip fires only from exactly `STMT_ISSUED` (`:265-273`).

§3.7 repayments: `installment_count` null when omitted (`repayments.py:88`); scope check is `employee.employer_id == case.employer_id`, after the arithmetic gate (`:63-75`); agree is the one transition where ownership is checked after body validation, case-status gate is `ERR_INVALID_STATE` and runs after the row's own state (`:128-140`); renegotiate accepts but **discards** `installment_count`, and `overpayment_tax_year` is not revisable (`:148-169`); the arithmetic gate precedes the state gate so it wins even on a non-`AGREED` row (`:155-158`); collection link two sweeps the **case**, not just the repayment's employee (`:194-203`); link three recomputes affected employees once each in ascending `employee_id`, links four/five conditional on something having been voided (`:206-212`); `write_off_reason` 1–2000 and write-off recomputes nothing (`:221-227`).

§3.8 notices: FK order employer→agency→case (`notices.py:46-51`); the attached case's `status` is not examined, so a `CLOSED` case accepts attachment (`:50-62`); `response_narrative` 1–4000, overdue tested after state and before the ceiling (`:34,130-133`); draft waiver ceiling is `ERR_WAIVER_EXCEEDS_ASSESSMENT` and an omitted value is not tested against a stored one (`:134-137`); omitted abatement fields retain prior values and `abatement_round` bumps even with nothing argued (`:139-148`); `info_request_note` ≤2000 with no minimum, persisted nowhere (`:174-183`); `agency_decision_reference` 1–120 and retained when omitted (`:192-204`); record-outcome permitted at abatement `NONE` or `REQUESTED`, `ERR_ALREADY_TERMINAL` once decided (`:198-204`); case sync conditional on a resolving `correction_case_id` but the **employer sync is unconditional** (`:225-228`).

§3.9 remediations: `owner_user_id` 1–120 and `target_date` both required (`remediations.py:24-25`); assign gate split `ERR_INVALID_STATE`/`ERR_ALREADY_TERMINAL`, `target_date` untouched when omitted, no rollup (`:99-109`); `evidence_reference` 1–500, unowned `OPEN` → `ERR_INVALID_STATE` and that test not re-applied from `VERIFICATION_FAILED` (`:118-128`); `passed` required boolean, `verification_note` ≤2000 persisted nowhere, SoD compared after the state gate (`:137-145`); on the failed branch the employer recomputation runs but lands on the same value so the row is not touched (`:151-157`).

§2.9 — revise — mismatch — "a wage repayment's employee must be the same employee as the statement it affects" replaced with the employer-based check impl performs, plus the note that repayments are never checked against statements — `repayments.py:74-75`

### Orchestrator verification of Step 9

- `PRD_COMPLETED.md` is **NOT** byte-identical to `PRD_FINALIZED.md` (69 diff hunks, +25,024 chars) — the scan genuinely ran.
- Heading count intact at 28; file still ends at a real section boundary (`| ERR_WAIVER_EXCEEDS_ASSESSMENT | 422 |`, last row of the §5 error table).
- All three passes' signature edits survive simultaneously in the final file (grep-confirmed: pass 1's §2.3 insertion-order tie-break, pass 1's §2.3 pagination-whitespace clause, pass 2's §2.11 conditional-`version`-bump wording) — no pass reverted another's work.
- `workspace/implementation/` has no file modified after the 10:58 all-green verification sweep, so the green result stands unaffected by Steps 8 and 9 (both of which only wrote PRD files).
- Final cleanup: `__pycache__` directories and `workspace/sweep.log` removed; the eight `results.{1..8}.json` artifacts from the passing sweep are retained per the pipeline output spec.

**PIPELINE COMPLETE** — Steps 1 through 9 all finished; `workspace/PRD_COMPLETED.md` written.
