# Worklog — task_2545_public_funds_deposit_collateralization

## Step 1: Create task directory — 2026-09-03T08:46:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2545_public_funds_deposit_collateralization` and its `workspace/` subdirectory. Index 2545 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no index was auto-allocated (32 concurrent pipelines on this host would collide).

## Step 2: Generate scaffold — 2026-09-03T10:45:00.000Z

All three scaffold artifacts for task 2545 are complete and the lint is clean.

## What was finished this session

`SCAFFOLD_CORNER_DESIGN.yaml` got its last two sections appended via chunked `cat >>`:

- **`cross_cutting_complexity_layers`** (8 instances): one OCC instance per §1.2.1 `concurrency_rules` entry — `occ_stale_agreement_version_rejected_on_second_allocation` (412 `ERR_STALE_AGREEMENT_VERSION`, re-GET makes the byte-identical payload succeed), `occ_stale_depository_version_rejected_on_second_mtm_run` (412 `ERR_STALE_DEPOSITORY_VERSION` with a window that is legally 4h clear, proving priority 67 could not have fired, and no `MarkToMarketRun` row created), `occ_stale_deposit_account_version_rejected_then_forecast_supersedes` (412 leaves forecast 1 `OPEN`; fresh version supersedes it; a different `cycle_label` never supersedes) — plus `version_increments_on_every_write_and_never_on_read` (re-posting an identical price still bumps version), `pagination_with_filtering_on_collateral_assets` (filtered `total_count` 4 of 6, `limit 101` → 400), `derived_field_reconciliation_after_repricing_an_allocated_asset` (one price post re-derives a five-level chain; coverage moves 4977 → exactly 4480 bps with par unchanged), and two `excluded_because` stubs citing `depository_suspension_depth4_cascade_to_runoff_forecast` and `runoff_projection_peak_window_vs_period_end`.
- **`consistency_model`** (1 instance): `immediate_visibility_of_derived_rollups_in_the_deposit_response` — the deposit's own 200 already carries 25,000,000 / 75,000,000 / 10500 bps / 78,750,000, and the sibling account's retroactive re-derivation (10,500,000) plus unit and depository rollups (110,000,000 / 85,000,000 / 89,250,000) are readable on the very next call.

## Two defects found and fixed

1. **All 24 `excluded_because` stubs were missing the required `grounds` key** (SKILL.md §1.9 stub contract = name + claim_type + grounds + excluded_because, no `test_recipe`). Added scaffold-specific `grounds` to every stub via a scripted insertion; verified all 83 instances now carry `grounds`, all stub citations resolve by `name` in `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, and no name collides across the two design files.
2. **A genuine internal inconsistency in `SCAFFOLD.yaml`**: validation priority 75 states `PUBLIC_UNIT <- PublicUnitTreasurer (owner) or StateRegulator (pooled beneficiary)`, but `POST /pledge-agreements/{id}/signatures` declared `roles: [BankComplianceOfficer, PublicUnitTreasurer, Custodian]` — so the pooled-program signature path in §1.8 was unreachable (this was the single lint violation). Added `StateRegulator` to that endpoint's roles, noted the pooled-only restriction in its description, and added the matching `shared_operations` line to the StateRegulator role.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2545_public_funds_deposit_collateralization/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2545_public_funds_deposit_collateralization/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2545_public_funds_deposit_collateralization/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    62
  §1.1 entities declared:     14
  §1.8 instances scanned:     20
  §1.9 instances scanned:     59
  Calls scanned (§1.8+§1.9):  1318

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Final line counts

| File | Lines | Structure |
|---|---|---|
| `SCAFFOLD.yaml` | **2396** | 14 top-level keys (§1.0–§1.7); contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`; 14 entities, 62 endpoints, 9 calculations, 3 concurrency rules |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | **2264** | single key `scaffold_difficulty_design`; all 9 difficulty rules, 20 instances |
| `SCAFFOLD_CORNER_DESIGN.yaml` | **5096** | single key `scaffold_corner_design`; 9 sections, 83 instances = 59 full `test_recipe` instances + 24 `excluded_because` stubs |

Every file parses under `yaml.safe_load` and ends at a real structural boundary. The isolation constraint held throughout — no sibling `task_*/` directory was listed, globbed, grepped, or read; the only sources consulted were the scenario text, the scaffold-generator skill (`SKILL.md`, `claim-extraction-guide.md`, `scaffold_lint.py`, and its own `examples/` file), and task 2545's own three files.

_Orchestrator verification: all three files parse under `yaml.safe_load`; top-level keys confirmed correct (SCAFFOLD.yaml carries neither design key)._

## Step 3: Copy shared files — 2026-09-03T10:45:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T11:05:00.000Z

PRD.md is complete and verified.

**Output:** `workspace/PRD.md` — **484 lines, 14,763 words**, built with 14 chunked `cat >>` appends (no single large Write; no truncation — line count advanced monotonically 29 → 484).

**Structure** (ends at a genuine boundary: the final row of the §5 table, no audit footer):
§1 Introduction · §2.1–2.9 globals · §3.1–3.9 business logic · §4 Endpoint Definitions · §5 Error Code Catalogue.

**Isolation honoured:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced; no sibling task directory was read.

## Hard Contract Reports

**Contract 1: Field-Name Coverage — PASS**
- 149 distinct entity field names extracted from SCAFFOLD.yaml `entities[]`: 149/149 present in PRD.md, and all 149 appear inside backticks (stricter check also passed).
- 75 distinct endpoint `input[]` field names: 75/75 present as backticked tokens.
- 24 endpoint-output-only / nested names spot-checked (`report_as_of`, the five `_ops` counters, `current_utc`, `to_iso8601`, `window_start`/`window_end`/`projected_balance_cents`, `credited_allocation_ids`, notes/reasons, etc.): all present.
- 91 enum literal values from `constraints:` : 91/91 present. 33 distinct state-machine state literals: 33/33 present.

**Contract 2: Rule Coverage — PASS**
- **Endpoints:** all **62** of §1.5 present in the §4 table with exact `Method | Path` match (mechanical `grep -F` check, 0 missing); table has exactly 62 data rows and exactly 4 columns.
- **Errors:** all **39** error IDs (scaffold has 39, not 37) appear in PRD.md and all 39 are rows of the 2-column §5 table.
- **Validations:** all **37** `validations[]` entries are covered by the 33-rung §2.7 ladder in priority order (rung 6 folds the three OCC checks, which are specified in full in §2.6 with their distinct error IDs). 36 of 37 error IDs are named literally inside §2.7; `ERR_STALE_AGREEMENT_VERSION` is named in §2.6 and cross-referenced from rung 6.
- **State machines:** all **11** machines / **52** transitions narrated in §3 (Depository, QualificationReview, DepositAccount.funding_status, DepositAccount.collateral_status, PledgeAgreement, CollateralAsset, PledgeAllocation, SubstitutionRequest, MarginCall, SafekeepingReceipt, RunoffForecast).
- **Calculations:** all **9** narrated with pinned rounding/evaluation order, including both dual-variant pairs (`insured_amount_determination` AGGREGATED_BY_UNIT/PER_ACCOUNT, `depository_risk_grade` SUPERVISORY/INTERNAL, `runoff_collateral_projection` PEAK_WINDOW/PERIOD_END), the PER_ALLOCATION_THEN_SUM aggregation order, the 7-step MTM order, and the pooled waterfall priority.
- **Constants:** every domain constant and calculation constant reproduced as a literal (clock default, open-ended sentinel, 3/2 round limits, 500,000,000,000 ceiling, 4/48/24/120-hour windows, zero tolerances, all six haircut bps, 1000/2/3 deficiency values, 0.50/0.30/0.20 weights, 2500, trailing-3, 8500/7000/5000 grade floors, 12000/9000/3000 coverage band, 25,000,000-cent insurance limit).
- **Concurrency:** all 3 OCC rules in §2.6 with their endpoints, `expected_*_version` fields and 412 error IDs; §2.6 states explicitly that no other endpoint accepts a version field.

**Contract 3: §3 Path Purity — PASS**
- §3 spans 209 lines. Backticked tokens beginning with `/`: **0**. Backticked tokens beginning with a bare HTTP method: **0**. Bare `GET|POST|PUT|PATCH|DELETE` as words anywhere in §3: **0**. Any unbackticked `/path`-shaped text in §3: **0**. Endpoints are referenced only by state-transition framing, role+action verb, or capability description. Paths appear only in §1/§2 (§2.6, §2.7, §2.8) and the §4 table, which is permitted.
- §3 also contains 0 markdown tables, 0 code fences, and 0 operator-syntax tokens (`:=`, `<=`, `>=`, `==`, `!=`).

**§2.2** is byte-identical to `skills/prd-bench-doc-generator/section-2.2-response-structure.md` (diff shows only the one blank separator line added after the block).

**Scaffold contradictions resolved** (decisions baked into the prose, consistent throughout): `value_adequacy_delta_cents` is null on submission and written only by the compliance leg; inverted/future MTM windows route to `ERR_MTM_WINDOW_OVERLAP` (per priority 67) while `ERR_INVALID_INTERVAL` covers allocation intervals and forecast-horizon inversion; `breach_deadline_at` is `cure_deadline_at`+24h at issuance and re-stamped to `escalated_at`+24h on escalation; cure-credit failures split between `ERR_COLLATERAL_TYPE_INELIGIBLE` (rung 13) and `ERR_CURE_ALLOCATION_INELIGIBLE` (rung 31) by ladder precedence.

_Orchestrator anti-truncation verification: `wc -l` = 484; `tail -20` ends on a complete `| \`ERR_CURE_EXCEEDS_OUTSTANDING\` | 422 Unprocessable Entity |` table row (genuine section boundary, not mid-sentence); `grep '^#'` shows the full expected §1 → §5 heading sequence with all of §2.1–2.9 and §3.1–3.9 present. No regeneration needed._

## Step 6: Generate implementation — 2026-09-03T12:20:00.000Z

(Launched concurrently with Step 5; Step 6 returned first, so its entry precedes Step 5's here. Step 5's entry follows below.)

## Implementation complete — task 2545 (Public Funds Deposit Collateralization)

`workspace/implementation/`

### Per-file line counts (3,566 lines total)
| File | Lines | File | Lines |
|---|---|---|---|
| `app.py` | 94 | `routes/registry.py` | 191 |
| `constants.py` | 171 | `routes/depositories.py` | 281 |
| `db.py` | 204 | `routes/accounts.py` | 330 |
| `errors.py` | 97 | `routes/agreements.py` | 340 |
| `response.py` | 72 | `routes/collateral.py` | 269 |
| `middleware.py` | 206 | `routes/substitutions.py` | 244 |
| `services/calc.py` | 245 | `routes/margin.py` | 383 |
| `services/state.py` | 428 | `start.sh` (chmod +x) | 10 |
| `routes/__init__.py`, `services/__init__.py` | 0 | `requirements.txt` | 1 |

`python3 -m compileall` passes; every file's tail ends at a real structural boundary (a closing `return`/statement, verified by `tail -n 3` on all 17 files). No `__pycache__` left behind.

### Route surface
Exactly **62 routes registered = 62 endpoints in PRD §4** (verified by diffing the count of PRD table rows against `url_map`, plus manual enumeration).

### Boot smoke
Two consecutive `bash start.sh` boots on port 18933 (mimicking `--isolation per-test-server`): both served HTTP 200 within 3s, returned an empty store (`total_count: 0`, no seeding), logical clock reset to `2026-08-01T00:00:00.000Z` on each fresh boot (no carry-over — clock advanced to 2026-09-09 in boot 1 was gone in boot 2), and the port was released after killing only that pid. No stray processes or listeners remain; no broad `pkill` was ever used.

### Functional end-to-end verification (8 scripted scenarios)
Exercised and confirmed correct: registry → qualification review cycle (attest/begin/return-for-info/re-attest, `round_count` cap 3) → account open with `group_sequence`/`pool_priority_rank` → deposits/withdrawals → agreement draft/circulate/3-party signature quorum/execution → asset registration with haircuts → pledge allocation with two-step valuation → coverage report (exactly the 10 documented values) → MTM run (SUPERVISORY + INTERNAL, 7 steps, risk components/grades) → margin call issuance, partial and exact cure (`CURED`, posture back to `COMPLIANT`) → escalation and breach via the sweep with the depth-4 suspension cascade (accounts `RESTRICTED/DEPOSITORY_SUSPENDED`, unit `ESCALATED`, forecast `STALE`+`requires_reforecast`) → pooled waterfall (ordering by rank ASC / required DESC, exact pot identity, `unallocated_collateral_cents`) → substitution fork-join settle, reject, withdraw → safekeeping receipt confirm/EXCEPTION → forecast PEAK vs PERIOD_END variants and supersession → all three OCC 412s → ladder spot checks (401/403/404/400/409/422 with the right `error_id`s). Spot-checked arithmetic matched hand computation to the cent (e.g. `unpledged_capacity_cents` 9,285,714 → 9,100,000 with half-up at .72).

### One fidelity fix made this session
`POST /margin-calls/{id}/cure` was rejecting an empty `credited_allocation_ids` array with `ERR_INVALID_REQUEST`. PRD §2.7 rung 5 enumerates non-emptiness for `projected_windows` only, so an empty array is now shape-valid and simply credits zero (`ISSUED → PARTIALLY_CURED`, `cured_cents` unchanged). A missing or non-array field still yields 400, unknown ids still yield 404 per rung 4.

Note: several apparent "failures" during smoke testing turned out to be faithful behavior, not bugs — single-custodian allocations legitimately breach a 6000 bps concentration limit; a cure allocation created at the same instant as the run's `as_of` is ineligible ("strictly after"); an `ISSUED` call already past `breach_deadline_at` never escalates (the sweep's escalation predicate requires standing *before* it); `PUBLIC_UNIT` on a `POOLED_PROGRAM` agreement is stamped by a `StateRegulator`; and omitting an OCC field is a 400 since PRD §2.6 declares all three non-optional.

## Step 5: Generate unit tests — 2026-09-03T13:35:00.000Z

Generation is complete. Both output directories are final and verified.

## Files and line counts

`test_helpers/` (9 files, 2616 lines)
| file | lines |
|---|---|
| `__init__.py` | 52 |
| `api_client.py` | 316 |
| `api_errors.py` | 93 |
| `assertions.py` | 432 |
| `constants.py` | 103 |
| `factories.py` | 259 |
| `fixtures.py` | 749 |
| `test_users.py` | 86 |
| `types.py` | 526 |

`test_suite/` (19 files, 7397 lines)
| file | lines | tests |
|---|---|---|
| `conftest.py` | 58 | — |
| `test_01_dual_variant_calculations.py` | 384 | 6 |
| `test_02_combinatorial_formulas.py` | 324 | 6 |
| `test_03_non_linear_state_machines.py` | 267 | 5 |
| `test_04_transitive_cascades.py` | 280 | 4 |
| `test_05_priority_pair_conflicts.py` | 241 | 4 |
| `test_06_boundary_precision.py` | 204 | 4 |
| `test_07_cross_entity_state_dependency.py` | 266 | 4 |
| `test_08_resource_temporal_overlap.py` | 351 | 4 |
| `test_09_compensating_invariants.py` | 312 | 4 |
| `test_10_entities.py` | 627 | 13 |
| `test_11_state_machines.py` | 749 | 10 |
| `test_12_calculations.py` | 704 | 8 |
| `test_13_validations.py` | 1422 | 16 |
| `test_14_endpoints.py` | 243 | 2 |
| `test_15_errors.py` | 77 | 1 |
| `test_16_rbac.py` | 184 | 2 |
| `test_17_cross_cutting.py` | 595 | 6 |
| `test_18_consistency.py` | 109 | 1 |

**Total: 100 tests, 10,013 lines across both directories.**

## Verification passes (all green)

- **PRD-citation pass** — every `PRD: "..."` block in all 28 files is a verbatim, grep-survivable, non-abbreviated PRD sentence/bullet/table row: `misses: 0`.
- **Design-citation pass** — 100 tests, each with exactly one trailing `Design:` line, all resolving to real non-stub instances. Queue A: 20/20 difficulty instances consumed, every one by ≥2 tests. Queue B: 59/59 non-stub corner instances consumed, every one by ≥1 test. No untagged, dual-tagged, stub-pointing or dangling tags.
- **Stub cross-references** — all 24 `excluded_because:` corner stubs point at a real `SCAFFOLD_DIFFICULTY_DESIGN.yaml` instance name; none translated into a test.
- **Static** — `pyflakes` clean on every file (removed three now-dead imports from `fixtures.py`); `test_helpers` imports cleanly; every file's last AST node ends on its last non-blank line (all tails are complete functions/classes/assignments).

## Instances consumed this session (final two files)

`test_17_cross_cutting.py` — all 6 non-stub `cross_cutting_complexity_layers` instances: `occ_stale_agreement_version_rejected_on_second_allocation`, `occ_stale_depository_version_rejected_on_second_mtm_run`, `version_increments_on_every_write_and_never_on_read`, `pagination_with_filtering_on_collateral_assets`, `occ_stale_deposit_account_version_rejected_then_forecast_supersedes`, `derived_field_reconciliation_after_repricing_an_allocated_asset`.

`test_18_consistency.py` — the single `consistency_model` instance `immediate_visibility_of_derived_rollups_in_the_deposit_response`.

## Instances SKIPPED

**None.** Every non-stub instance in both indices is covered.

## Sub-assertions corrected or dropped (design contradicted or under-determined by the PRD)

- `version_increments_on_every_write_and_never_on_read` — design set the asset up on a **DRAFT** depository; PRD §3.4 states "The depository must be `APPROVED` before any collateral may be registered against it", so the depository is carried to APPROVED. The custodian stays PENDING_APPROVAL as designed (no rule gates registration on custodian approval).
- `pagination_with_filtering_on_collateral_assets` — dropped the "muni_1 keeps its position in the unfiltered ordering" sub-assertion: all six assets share one `created_at`, so the PRD's `created_at ascending` sort does not uniquely derive tie order. Replaced with an assertion that the row is still present and `total_count` is still 6 after the mutation.
- Carried from earlier sessions: `Depository.deposit_account_count` (field absent from PRD); pooled post-release `exposure_status == WATCH` (PRD derives NORMAL); `value_adequacy_delta_cents` non-null at submission (PRD says null until compliance approval); `participant_account_count == 1` for an unfunded pooled account (PRD counts only funded participants); a freshly issued safekeeping receipt asserted `ISSUED` then confirmed via the regulator (PRD line 357/359), not `CONFIRMED` at 201; the fifth idempotence sweep asserts the three action counters zero with `stale_priced_asset_count == 1` (PRD-derived, design said all-zero); the "GET /custodians has no 'Officer Custody'" check dropped because the PRD exposes no custodian list endpoint.

## Step 7: Run tests and iterate — 2026-09-03T12:55:00.000Z

All 100 tests pass in all 8 rounds.

## Summary

**Iterations run:** 2 sweeps (8 parallel rounds each, under `setsid nohup`).

**Iteration 1 baseline:** 64/100, identical in all 8 rounds — fully deterministic, so no load-induced flakiness was in play. The 36 failures collapsed to 4 root causes.

### Tests deleted (PRD silence)

- `test_13_validations.py::test_circulation_needs_both_halves_of_custodian_eligibility` — removed 3 assertions on a `circulated_at` response field (`stalled["circulated_at"] is None`, `also_stalled["circulated_at"] is None`, `circulated["circulated_at"] == DEFAULT_CLOCK_UTC`). **COMPUTED-FIELD SILENCE / STEP 1c partial coverage:** PRD never names a `circulated_at` field anywhere; §3.3's explicit enumeration of a drafted agreement's null stamps lists only `depository_signed_at`, `public_unit_signed_at`, `custodian_signed_at`, `executed_at`, `terminated_at`. Adding the field to the implementation would have violated the "no non-PRD-traceable response field" rule. The covered `status` (`DRAFT` / `PENDING_SIGNATURES`) and `ERR_CUSTODIAN_NOT_ELIGIBLE` assertions were kept, so the test still enforces the rung-12 rule that drove its generation (scaffold rule: validations / custodian tri-party-capability + approval conjunction for circulation). No whole test was deleted.

### Fixes to `test_helpers/`

- `test_helpers/constants.py`: added `clock_stamp(instant)`, which renders a logical-clock instant in the canonical form PRD §2.4 pins ("an ISO 8601 UTC timestamp with three fractional digits", `updated_at` "refreshed on every mutation using the same format", and every `_at` / `as_of` stamp "read from the logical clock"). So an instant set to `2026-08-01T00:00:00Z` reads back `2026-08-01T00:00:00.000Z`.

### Fixes to `test_suite/` (test-vs-PRD consistency, STEP 2)

- 63 server-minted-stamp equality assertions across 12 files (test_03, 05, 07, 08, 09, 10, 11, 12, 13, 14, 16, 17) were comparing against the bare clock string the operator *set*, contradicting PRD §2.4's three-fractional-digit format verbatim. Each RHS is now wrapped in `clock_stamp(...)`. The decisive evidence was `test_17_cross_cutting.py` asserting `created_at`/`updated_at` equal to the bare string — the implementation's rendering is the PRD-correct one. The 5 remaining unwrapped clock comparisons were verified to be client-echoed fields (`last_mtm_window_end`, `window_end`, `effective_from`) and already passed.
- `test_18_consistency.py`: `collateral_status` `DEFICIENT` → `UNSECURED` on both the written and the sibling account, and unit `exposure_status` `WATCH` → `NORMAL`. PRD §3.2 lists six transitions and `UNSECURED → DEFICIENT` requires "`assigned_collateral_value_cents` is greater than zero"; with no collateral pledged at all, assigned is 0, so the account stays `UNSECURED`, and §3.1's ordered exposure read then yields `NORMAL`. No assertion was weakened — each was corrected to the value PRD uniquely determines.

### Fixes to `implementation/`

- `services/state.py` + `routes/accounts.py`: siblings rewritten by a balance move were not being versioned. PRD §2.9 requires "every entity whose stored fields actually changed has had its `updated_at` refreshed and its `version` incremented by 1", while §3.2's chain re-runs insured-amount determination "for every member of the touched account's insurance group" and §3.5 re-runs the waterfall rewriting "every participant's share". Added `snapshot_accounts()` / `version_changed_accounts(before, skip_ids=...)` to `state.py` and wired them around `recompute_all` in both `credit_deposit` and `debit_withdrawal`, so exactly the accounts whose stored derived figures actually differ get `db.touch`ed; accounts merely read come out byte-identical and are untouched. Storage remains in-memory dicts with nothing seeded.

### Final sweep verification

All 8 `results.{1..8}.json` files exist in `workspace/implementation/` and each reports `passed == total`:

- round 1: 100/100, 0 failed, 0 errors, 187s
- round 2: 100/100, 0 failed, 0 errors, 187s
- round 3: 100/100, 0 failed, 0 errors, 187s
- round 4: 100/100, 0 failed, 0 errors, 187s
- round 5: 100/100, 0 failed, 0 errors, 187s
- round 6: 100/100, 0 failed, 0 errors, 187s
- round 7: 100/100, 0 failed, 0 errors, 187s
- round 8: 100/100, 0 failed, 0 errors, 187s

Union of failures across all 8 rounds: 0. No `pytest.mark.skip`/`xfail` anywhere; `pyflakes` clean on `test_suite/` and `implementation/` (one pre-existing unused import in `routes/margin.py`). Scratch analysis scripts were removed from `workspace/`.

_Orchestrator independent verification: all 8 `results.{1..8}.json` exist (timestamped 12:51, ~29.4 KB each) and each parses to `passed=100, failed=0, total=100, errors=0`. Step 8 is NOT skipped — Step 7 applied 1 partial deletion, test_helpers/test_suite fixes, and 1 implementation fix._

## Step 8: Finalize PRD — 2026-09-03T13:05:00.000Z

Done. `PRD_FINALIZED.md` written with four in-place paragraph revisions.

## Line counts
- PRD.md: **484 lines**; PRD_FINALIZED.md: **484 lines** (0.0% delta — this PRD keeps each paragraph on one line, so all four edits are intra-line; words grew 14763 → 15172, **+2.8%**). File still ends at the last row of the §5 error table (`ERR_CURE_EXCEEDS_OUTSTANDING`).

## Changes
- **§2.4 — revise —** pinned that every stamp minted from the logical clock (including `created_at`, `updated_at`, `report_as_of`, `current_utc`) renders in the same three-fractional-digit ISO 8601 form, so a clock at `2026-08-01T00:00:00Z` reads back as `...00.000Z`; and that client-supplied instants (`effective_from`/`effective_to`, `window_start`/`window_end`, forecast horizon and window bounds, and the copied `last_mtm_window_end`) are echoed verbatim, with the substitution-minted `effective_from` and the open-ended sentinel excepted — `db.py:72-109` (`format_iso`, `Ts.system`, `Ts.of`), `response.py:36-43`.
- **§2.9 — revise —** replaced the universal claim "every entity whose stored fields actually changed has had its `updated_at` refreshed and its `version` incremented by 1" with the narrower rule the impl actually follows: versioning happens where a request writes a record's own fields or where §3 names the increment; purely re-derived records (public units, pooled programs, assets whose pledged/available par shifted, depositories whose margin-call count and posture were recounted) keep their `version` — `services/state.py:8-12`, `db.py:187-192`.
- **§3.2 — revise —** the balance-move chain now ends by versioning not only the written account but every other deposit account the chain actually rewrote (group sibling, or pool participant at any depository), with the eight stored derived figures named as the test, and explicitly leaving unchanged accounts, units, depositories and pools untouched — `services/state.py:260-297`, `routes/accounts.py:148-154, 173-177`.
- **§3.8 — revise —** pinned that `credited_allocation_ids` must be present and an array of id strings but need not be non-empty; an empty array is shape-valid, credits zero, and is processed like any credit below `outstanding_cents` — `routes/margin.py:277-287, 315-325`.

No PRD edit was made for two Step 7 items: the deleted `circulated_at` assertions (`routes/agreements.py:144-162` sets no such field, and PRD never names it, so leaving PRD silent reproduces the impl), and the `test_18` `DEFICIENT → UNSECURED` / `WATCH → NORMAL` fixture corrections (§3.2's six transitions and §3.1's ordered exposure read already determine them; `services/calc.py:133-162` matches verbatim).

## Per-edit pre-edit search log

**Edit 1 — §2.4.** (a) Subject: rendering of every timestamp the API emits. (b) Enumerated: `db.py` `format_iso`/`Ts`/`Ts.system`/`Ts.of`/`SENTINEL_TS`/`plus_hours`/`now_ts`/`now_text`; `response.py:_value` (renders `Ts.text`) and `_meta`; grepped all 40 `now_ts()`/`now_text()`/`req_ts`/`opt_ts`/`Ts.`/`plus_hours` sites — server-minted set (`approved_at`, `decided_at`, three `_signed_at`, `executed_at`, `terminated_at`, `priced_at` on both register and reprice, `released_at` from `state.release_allocation` and from settlement, `compliance_approved_at`, `custodian_acked_at`, `settled_at`, `superseded_at`, `confirmed_at`, receipt/run `as_of`, `cure_deadline_at`, `breach_deadline_at`, `escalated_at`, `cured_at`, `report_as_of`, both `current_utc`) vs. client-echoed set (`effective_from`, `effective_to`, `window_start`, `window_end`, `horizon_start`, `horizon_end`, `projected_windows[]` bounds, `last_mtm_window_end`). (c) Adjustment: the first draft listed `effective_from`/`effective_to` flatly as client-echoed, which would have mis-described `routes/substitutions.py:175` (settlement mints `effective_from` from the clock) and `routes/collateral.py:173` (sentinel default); added the closing sentence carving out both cases before committing.

**Edit 2 — §2.9.** (a) Subject: which entities get `updated_at`/`version` moved. (b) Enumerated: every `db.touch` callsite (34, across `registry.py`, `depositories.py`, `accounts.py`, `agreements.py`, `collateral.py`, `substitutions.py`, `margin.py`, `state.py`) plus `db.touch` itself and `state.recompute_all` (which mutates derived fields with no `touch`). Confirmed `public_units` and `pooled_programs` are never touched after creation; `collateral_assets` are not touched by allocation create/release (`collateral.py:210-227, 256-269`); the depository is not touched by a cure even though `open_margin_call_count`/`collateral_posture` change (`margin.py:318-326`); the breach path with a non-`APPROVED` depository forces `collateral_posture` FROZEN with no version bump (`margin.py:359-369`). (c) Adjustment: dropped an initial "only where §3 explicitly names an increment" formulation, which would have mis-described `registry.py:71-72` (custodian approve — §3.1 never mentions `version`) and every created-record path; widened to "writes its own stored fields directly … or where §3 says explicitly".

**Edit 3 — §3.2.** (a) Subject: account versioning during a balance move. (b) Enumerated: `state.snapshot_accounts`/`version_changed_accounts`/`ACCOUNT_DERIVED_FIELDS` (`state.py:260-297`), both callsites (`accounts.py:148-155, 173-178`), `recompute_all` ordering, `_recompute_requirements` (whole insurance group), `_recompute_assigned_and_pools` + `_pool_participants` (all pools, all depositories), `_recompute_units`/`_recompute_depositories` (no touch); grepped to confirm no other route calls `version_changed_accounts`. (c) Adjustment: scoped the sentence to "this chain" (the balance-move chain) rather than to recomputation generally, so it cannot be read onto `create_allocation`, `release`, `post_price`, `mark_ineligible`, `terminate_agreement`, `settle` or `cure` — none of which version affected accounts; and used "wherever that account sits" rather than "of the same depository", since the pool waterfall reaches participants at other banks.

**Edit 4 — §3.8.** (a) Subject: request shape of `credited_allocation_ids` and the zero-credit outcome. (b) Enumerated: `margin.py:_credited_allocations` (missing/non-array → 400, non-string item → 400, unknown id → `mw.resolve` 404 before the state check), `cure_call:290-327` (credit sum, `> outstanding` overage test, `ISSUED → PARTIALLY_CURED` vs `CURED` branch), `accounts.py:_read_windows:236-239` (the one field that *is* non-emptiness-checked), `middleware.req_int/req_ts` for the contrast. (c) Adjustment: said "processed like any other credit smaller than the outstanding amount" rather than naming the resulting status, because the impl's zero-credit path leaves a `PARTIALLY_CURED` call self-looping and an `ESCALATED` call in `ESCALATED` — naming only `PARTIALLY_CURED` would have been a false universal; also rephrased the following clause from "Every identifier … must be ACTIVE" back to "Every allocation actually offered must be ACTIVE" to keep the original per-allocation conditions attached to allocations.

## Step 9: Complete PRD — 2026-09-03T13:35:00.000Z

Run as **three sequential file-partitioned passes** over `implementation/` rather than one monolithic scan. Orchestrator rationale (decision recorded per AUTONOMY): a single subagent asked to walk 17 files / 3,566 lines of Flask implementation against a 484-line PRD has, in prior runs of this pipeline, returned a PRD_COMPLETED.md byte-identical to its input — i.e. the scan silently did not happen. Partitioning by file guarantees every module is examined under its own budget, and each pass verified the diff line count grew (15 → 24 → 36 changed lines), which is direct evidence the scan actually ran. Each pass was given read access to the other partitions for global-consistency checking, so the NO-NEW-MISMATCH discipline was preserved across the boundary.

### PASS A — app.py, constants.py, db.py, errors.py, response.py, middleware.py, routes/registry.py, routes/depositories.py

**Counts:** 13 ambiguity-pins, 2 mismatch-revisions. 15 changed lines.

- §2.1 — revise — ambiguity — headers that are whitespace-only count as empty, and both headers are compared after trimming — `middleware.py:17-28`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A–Z0–9` — `response.py:10,13-14`
- §2.2 — revise — **mismatch** — `api_request_timestamp` is read from the **logical clock**, not wall-clock (§2.4's clock-minted list omitted it) — `response.py:20`
- §2.2 — insert — ambiguity — unknown path or unsupported method → `ERR_RESOURCE_NOT_FOUND` 404; trailing slash tolerated; no 5xx ever, unhandled failures surface as `ERR_INVALID_REQUEST` 400 — `app.py:19,61-81`
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` is `ERR_INVALID_REQUEST`, never clamped — `middleware.py:166-190`
- §2.3 — revise — ambiguity — ties on `created_at` (the common case under a frozen clock) break by creation order; empty filter param = absent; enum filters validated (400 on unknown value) while id filters are not (empty page, not 404) — `db.py:195-197`, `middleware.py:193-202`
- §2.4 — revise — ambiguity — `updated_at` equals `created_at` on an unmutated record — `db.py:161-173`
- §2.4 — revise — ambiguity — body instants accepted with `Z`, an explicit offset, or none (read as UTC); echoed verbatim after whitespace-stripping; compared as UTC — `db.py:53-69,105-109`
- §2.7 r4 — insert — ambiguity — a body FK that is absent/null/non-string is a rung-5 shape failure, not a 404 — `middleware.py:39-47`
- §2.7 r5 — revise — **mismatch** — `capital_ratio_bps` also permits zero (rung 5 listed only the two receipt fields) — `depositories.py:52-59`
- §2.7 r5 — insert — ambiguity — absent/unparseable body read as `{}`; non-object JSON body is 400; optional field as `null` = omitted (takes default) while required `null` fails; booleans rejected as integers; two-letter state codes validated only as non-empty strings — `middleware.py:51-57,60-61,112-121`, `registry.py:96,156`, `depositories.py:51`
- §2.9 — insert — ambiguity — the whole derived graph is re-derived at the start of **every** request including reads (so clock-dependent interval mirrors are current on the next read), bumping no `version` and advancing no `collateral_status` — `app.py:40-46`, `state.py:86-94`
- §3.1 — revise — ambiguity — custodian approval admissible only from `PENDING_APPROVAL` (else `ERR_INVALID_STATE`) and increments `version` — `registry.py:64-74`
- §3.1 — insert — ambiguity — filed review's note/decision fields all begin null; filing admissible in any depository status except `DENIED`/`SUSPENDED`, so an `APPROVED` bank may file and attest a further package that cannot be taken under review — `depositories.py:147-164`
- §3.1 — revise — ambiguity — `attestation_note` stored (re-attestation overwrites it, leaves `info_request_note`); all four review endpoints reply with the review, never the depository; `decision_note` and `decided_at` written on both branches, ceiling recheck runs after the state gates and on `DENY` too; denial admissible from `UNDER_REVIEW` with or without an attestation — `depositories.py:204-208, 211, 228, 244, 252-281`

Checked and left alone because already uniquely pinned: the entire §5 error/status catalogue (byte-for-byte match with `errors.py:3-43`); every domain constant in `constants.py` (haircut table, capital-tier bounds and base percentages, mode/deficiency surcharges, 15000 cap, 25,000,000 insurance limit, 500,000,000,000 ceiling, 4h MTM gap, 48h price staleness, 24h escalation grace, cure tiers 24/48/120, zero tolerances, pool ranks and default 4, risk weights/thresholds/floor 9000/span 3000/cap 12000/2500 volatility/3 trailing runs, all registration defaults and ranges); the default clock and open-ended sentinel; UUID ids with no prefix; `version` starting at 1; the success/error envelope shapes and `has_more` formula; and the depository/custodian/pool/public-unit creation field sets and initial derived zeros.

### PASS B — routes/accounts.py, routes/agreements.py, routes/collateral.py

**Counts:** 1 mismatch-revision, 8 ambiguity-pins (10 Edit calls landing on 9 lines). Diff vs PRD_FINALIZED at exit: 24 changed lines.

- §3.2 — revise — mismatch — a new deposit account's `required_collateral_pct_bps` is **not** zero; the pre-response recomputation has already stored the full tier+mode+deficiency percentage even at zero balance — `routes/accounts.py:84,98` + `services/state.py:182-189`
- §2.7 rung 3 — insert — ambiguity — ownership precedes existence only for `open_account`'s body `public_unit_id`; in the other nine rung-3 operations the target (path id, or the FK whose owner is tested) resolves first, so 404 wins — `routes/accounts.py:56` vs `:275`, `routes/agreements.py:277`
- §3.3 — insert — ambiguity — a `PublicUnitTreasurer` reaching for `PUBLIC_UNIT` on a `POOLED_PROGRAM` agreement clears the ownership rung (no beneficiary account) and fails entitlement with `ERR_SIGNATURE_PARTY_MISMATCH` — `routes/agreements.py:176-197`
- §3.3 — insert — ambiguity — amendment on a pooled agreement is refused for **every** treasurer with `ERR_NOT_RESOURCE_OWNER`, leaving the move to the regulator — `routes/agreements.py:216`
- §3.3 — revise — ambiguity — `agreement_number` uniqueness spans all of the depository's agreements whatever their status; a `TERMINATED` number is not reusable — `routes/agreements.py:69-71`
- §3.4 — revise — ambiguity — `cusip` uniqueness spans all of the depository's assets whatever their `eligibility_status` — `routes/collateral.py:70-72`
- §3.9 — insert — ambiguity — filing a forecast consults neither the account's `funding_status` nor the depository's `approval_status` — `routes/accounts.py:271-289`
- §3.9 — insert — ambiguity — `projected_windows` is stored/echoed in submitted order with exactly the three documented keys; extra keys are discarded — `routes/accounts.py:235-254`, `response.py:36-43`
- §3.9 — insert — ambiguity — the horizon's `ERR_INVALID_INTERVAL` test runs before the window chain is walked — `routes/accounts.py:287-289`
- §3.9 — revise — ambiguity — the frozen `required_collateral_pct_bps` drives the projection but is not stored as a field on the forecast record — `routes/accounts.py:291,305-321`

Non-findings (verified pinned): the full rejection-ladder ordering in `create_allocation` (rungs 6→8→10→13→15→16→20→21→25→26→33) matches §2.7 exactly; the `apply_status=True` call sites are exactly the seven-plus-two triggers §3.2 lists for `collateral_status`; the coverage report returns exactly the ten documented values in order; the two-step valuation, receipt covering-set/discrepancy arithmetic and pooled-vs-dedicated assignment all already match §3.4/§3.5/§3.9.

### PASS C — routes/substitutions.py, routes/margin.py, services/calc.py, services/state.py

**Counts:** 10 ambiguity-pins, 2 mismatch-revisions (12 changed lines).

- §3.2 — insert — ambiguity — depository's `total_required_collateral_cents` sums only `FUNDED`/`RESTRICTED` accounts; `PENDING_FUNDING` requirements are excluded from the bank-level total — `services/state.py:337-341`
- §3.4 — insert — mismatch — per-allocation valuation is re-derived every request for **every** allocation regardless of `status`, so `RELEASED`/`SUBSTITUTED` allocations keep tracking current price rather than freezing at release; only `ACTIVE` ones feed aggregates (verified against all 8 aggregate sites incl. receipts) — `services/state.py:129-139`
- §3.6 — insert — ambiguity — the incoming leg of `value_adequacy_delta_cents` uses the asset's current price/haircut even if the asset has since become `INELIGIBLE` (no collateral-type gate on this branch) — `routes/substitutions.py:116`, `services/calc.py:71`
- §3.6 — revise — mismatch — settle's capacity test is **not** `available_par_cents >= incoming_par_cents`; it is the interval-aware par-capacity rule over `[clock, sentinel)` with the outgoing allocation **excluded** from occupancy; also added the missing `tri_party_capable` precondition — `routes/substitutions.py:168-181`, `services/state.py:400-418`
- §3.6 — insert — ambiguity — a non-originating officer's withdraw yields `ERR_NOT_RESOURCE_OWNER`, tested *after* the state check (so `SETTLED` → `ERR_INVALID_STATE`); scoped so §2.7 rung 3's "exactly ten operations" stays true — `routes/substitutions.py:232-240`
- §3.7 — insert — ambiguity — an mtm-run is admissible in every `approval_status` except `DENIED`; a `SUSPENDED` depository is still valued — `routes/margin.py:104-105`
- §3.7 — insert — ambiguity — "previous run" = greatest `run_index`; the 4-hour buffer is a signed gap, so a wholly-backdated non-intersecting window also fails — `routes/margin.py:53-57`
- §3.7 — insert — ambiguity — documentation numerator requires the executed agreement to belong to *that same* depository (cross-bank agreements don't count), while the pooled path is pool-wide — `routes/margin.py:82-89`
- §3.8 — insert — ambiguity — `credited_allocation_ids` elements are all shape-checked before any is resolved, and resolution precedes the call's status check — `routes/margin.py:277-296`
- §3.8 — insert — ambiguity — an `ESCALATED` call taking a partial credit self-loops in `ESCALATED`, never falling back to `PARTIALLY_CURED` — `routes/margin.py:320-324`
- §3.8 — insert ×2 — ambiguity + mismatch — (a) an `ISSUED`/`PARTIALLY_CURED` call already past `breach_deadline_at` matches neither sweep action and is stranded (escalation is the only route to `BREACHED`); escalation and breach cannot occur in one sweep; (b) the breach freeze is **sticky** and outranks the §3.7/§3.8 posture derivation — `collateral_posture` stays `FROZEN` forever — `routes/margin.py:349-369`, `services/state.py:363-368`
- §3.8 — insert — ambiguity — `suspended_depository_count` counts only `APPROVED → SUSPENDED` transitions, so it can fall below `breached_margin_call_count` — `routes/margin.py:363-369`

Behaviors checked and found already uniquely pinned: the fork-join transition matrix and ladder order in `open_request`/`custodian_ack`/`reject`; run steps one–seven incl. `INTERNAL` trailing-window averaging (average-then-weight) and all rounding modes; `derive_posture` and `open_margin_call_count`; the 9 `apply_status=True` trigger sites matching §3.2's list exactly; the dedicated-assignment/pooled-pot interval asymmetry (§3.5 already documents it); pool waterfall ordering and `pool_posture`; the 4-hop suspension cascade being unit-wide in hop four; `>=` vs `==` in `FULLY_PLEDGED` and `ROUND_FLOOR` vs truncate-toward-zero (both provably unobservable given non-negative inputs and the oversubscription bar).

### Step 9 totals

- Source `PRD_FINALIZED.md` 484 lines → `PRD_COMPLETED.md` 484 lines (this PRD holds one paragraph per line, so all edits are intra-line).
- **36 changed lines** (72 diff-side lines) across the three passes: **31 ambiguity-pins, 5 mismatch-revisions**.

_Orchestrator independent verification: `wc -l` = 484 for PRD.md / PRD_FINALIZED.md / PRD_COMPLETED.md; `cmp` confirms PRD_COMPLETED.md is NOT byte-identical to PRD_FINALIZED.md (so the scan genuinely ran); `diff | grep -c '^[<>]'` = 72; 26 headings intact through `## 5. Error Code Catalogue`; tail ends on the complete final §5 table row. Pipeline complete._
