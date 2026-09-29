# Worklog — task_2246_snap_retailer_authorization_redemption_compliance

## Step 1: Create task directory — 2026-09-01T11:00:40.225Z

Created `tasks/task_2246_snap_retailer_authorization_redemption_compliance/` and `workspace/` (pre-allocated directory name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T13:15:57.422Z

Note: first attempt terminated with an API `max_output_tokens` error (single monolithic Write). Relaunched with a chunked-write directive; second attempt succeeded.

All three artifacts are complete and the lint is clean.

**Files** (in `/home/ubuntu/github/CodingPRD/tasks/task_2246_snap_retailer_authorization_redemption_compliance/`)
- `SCAFFOLD.yaml` — 2,589 lines, §1.0–§1.7 only (no design keys).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1,895 lines, single key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 5,048 lines, single key `scaffold_corner_design`.

**Scaffold counts** — 15 entities (`graph` topology, self-referential `predecessor_store_id`, many-to-many `TerminalDeployment`, append-only `PenaltyLedgerEntry`); 11 state-machine dimensions over 10 entities (`parallel` shape); 2 OCC concurrency rules; 17 calculations; 21 validations (priorities 1–21); 74 endpoints; 57 errors; 7 roles (`segregation_of_duties`). `difficulty_level: beyond_expert`, layers = dual-variant calc, rate/threshold triggers, cascading side effects, derived-field reconciliation, optimistic concurrency; `consistency_model: immediate`.

**§1.8** — 9/9 difficulty rules, 25 instances (3/3/2/2/3/3/3/3/3), e.g. dual CMP basis variants (trailing-12 vs peak-3 selected by the 365-day seasoning), desk-vs-onsite staple criterion divergence, 5-level enforcement cascade, three priority-pair conflicts, strict-boundary pairs (69 vs 70 anomaly score, exactly 5000 bps Criterion B), travel-buffer and closed-interval overlap corners, and three compensating-invariant round trips (penalty ledger, depot units, inspector minutes).

**§1.9** — 125 corner instances across all nine sections (99 full test recipes + 26 `excluded_because` stubs citing named §1.8 instances): entities 13, state_machines 22, calculations 22, validations 33, endpoints 10, errors 5, rbac 7, cross_cutting 11, consistency_model 2.

**Coverage audit** — all 11 entity claim types, all 7 state-machine claim types, all 4 calculation claim types, Violation→Error / Satisfaction→Pass / Priority Ordering for the full priority ladder, all 6 endpoint patterns, allow+deny for all 7 roles plus the three segregation-of-duties prohibitions, both §1.2.1 OCC rules, and an inline audit table proving **57/57 error codes triggerable**. Verified programmatically: 0 unbound `${...}` placeholders in either design file, no name collisions between the 25 §1.8 and 125 §1.9 names, every stub citation resolves.

**Lint verdict** (verbatim):
```
Coverage
  §1.5 endpoints declared:    74
  §1.1 entities declared:     15
  §1.8 instances scanned:     25
  §1.9 instances scanned:     99
  Calls scanned (§1.8+§1.9):  1813

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
One SCAFFOLD.yaml fix was needed to reach clean: the two sub-resource list routes were renamed to `GET /sanction-cases/{id}/cmp-elections` and `GET /sanction-cases/{id}/penalty-ledger` (the FK reverse-reachability check requires the literal `{id}` parent segment); role tables and grounds references were updated to match. No sibling task directory was read, listed, or grepped at any point.

## Step 3: Copy shared files — 2026-09-01T13:15:57.422Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T13:30:21.166Z

PRD generation is complete.

**Output:** `workspace/PRD.md` — **537 lines**, written in 8 incremental calls (1 `Write` + 7 heredoc appends), each well under the 600-line cap. No content was reduced to fit the budget. File ends at §5; no audit footer inside the document.

**Section inventory**
- §1 Introduction (fragmented-systems pain point → four system jobs → logical-clock + integer-cents design commitments)
- §2 Global Specifications: 2.1 Role-Based Access Control (7 roles, `X-User-ID`/`X-User-Role`) · 2.2 API Response Structure (verbatim, byte-for-byte verified) · 2.3 Pagination · 2.4 Logical Clock & Deadline Arithmetic · 2.5 Identity/Timestamps/Version Semantics · 2.6 OCC on Store and Case Snapshots · 2.7 Integer Cents, Basis Points, Rounding Discipline · 2.8 Validation Precedence (all 21 ordered rules with every `applies_to` path) · 2.9 Path Resolution & Reference Integrity · 2.10 Interval Conventions & Aggregate Capacity Ceilings · 2.11 Segregation of Duties · 2.12 Conservation Invariants · 2.13 The Two Independent Store Status Dimensions
- §3 Business Logic & Workflows: 3.1 Onboarding & Owner Rollup · 3.2 Application & Two Eligibility Routes · 3.3 Field Verification & Deficiency Cycles · 3.4 Authorization Decision, FNS Numbering, Transfers · 3.5 EBT Terminal Provisioning & Equipment Orders · 3.6 POS Eligibility Screening & Split Tender · 3.7 Redemption Monitoring, Reconciliation, Anomaly Scoring · 3.8 Investigations, Evidence Decay, Substantiation · 3.9 Charge Letters, Determinations, Civil Money Penalty · 3.10 Administrative Review, Finality, Enforcement
- §4 Endpoint Definitions — 74 rows (Method | Path | Description | Authorized Role(s)), matches scaffold count exactly
- §5 Error Code Catalogue — 57 rows, matches scaffold count exactly

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 163 required, 163 present, 0 missing
- endpoints[].request_body / input: 84 required, 84 present, 0 missing
- endpoints[].query_params / path_params: all present, 0 missing
- nested/auxiliary identifiers (category, variety_key, unit_count, is_perishable,
  sku, item_class, unit_price_cents, qty, item_code, evidence_type, observed_at,
  note, current_utc, outcome, id, created_at, updated_at, version): 0 missing
- error ids: 57/57 · roles: 7/7 · states (11 dimensions): 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 21 checked, 21 expressed (ordered list, §2.8), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoint +
  expected_store_version / expected_sanction_case_version + error id + 412), 0 missing
- state_machines[].transitions: all transitions across 11 dimensions expressed, 0 missing
- calculations[]: 17 checked, 17 fully expressed, 0 missing
- validation conditions: all 57 error ids matchable to a stated condition, 0 missing
- endpoints[].side_effects + cross-entity cascades + applies_to scopes: 0 missing
- sibling-branch symmetry: equal density on desk vs on-site staple variant,
  TRAILING_12_PERIOD_AVERAGE vs PEAK_3_PERIOD_AVERAGE, SUSTAINED/REVERSED/REMANDED,
  NO_ELIGIBLE_ITEMS vs INSUFFICIENT_SPLIT_TENDER, three deployment exits — 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 1001
- tokens starting with `/`: 0 · bare HTTP-method tokens: 0 · method+path tokens: 0
Status: PASS
```

**Audit notes**
- Two scanner hits were false positives: `SNAP` (in `PosTransaction.flagged_line_skus`) and `CMP` (in `SanctionCase.cmp_basis_period_ids`) are ordinary prose words inside scaffold field *descriptions*, not enum values.
- The calculation variant labels `DESK_VARIETY_FIRST` / `ONSITE_DEPTH_FIRST` do not appear as literal identifiers; no API field carries them as a value, and both variants' full semantics (including their divergence on shallow-but-broad inventory) are specified in §3.2 and §3.3. Outside Contract 1's scope.
- Resolved a scaffold internal contradiction on `Store.redemption_flag_level` tie-breaking (entity description says latest `created_at`; the calculation says older row wins) by noting `period_index` is unique per store so ties cannot arise, then stating the earlier-`created_at` fallback.
- `hold_reason_code` selection is left partly implicit by the scaffold; the PRD states an explicit, non-contradictory mapping across `STAPLE_STOCK_INSUFFICIENT`, `SHELF_DISCREPANCY`, `DEPTH_OF_STOCK_INSUFFICIENT`, `NO_ACCESS`, `INVESTIGATION_HOLD`.
- Contract reports appear only here, never in PRD.md or any sibling file. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

## Step 5: Generate unit tests — 2026-09-01T15:19:09.807Z

Verification is clean across the whole suite. Final state:

**Files created**

`test_helpers/` — 9 modules: `types.py`, `api_errors.py` (57-member `ApiErrorId`), `constants.py`, `api_client.py`, `test_users.py`, `factories.py`, `assertions.py`, `fixtures.py`, `__init__.py`.

`test_suite/` — `conftest.py` plus 19 test modules, **147 tests** total:
- Queue A (difficulty, 50 tests / 25 instances): `test_10_staple_eligibility_variants.py` (2), `test_11_cmp_basis_variants.py` (4), `test_12_penalty_and_fee_formulas.py` (6), `test_13_application_and_store_state_paths.py` (4), `test_14_cascades.py` (4), `test_15_validation_priority_pairs.py` (6), `test_16_boundaries.py` (6), `test_17_cross_entity_dependencies.py` (6), `test_18_interval_and_capacity.py` (6), `test_19_conservation_invariants.py` (6).
- Queue B (corner, 97 tests / 97 instances): `test_20_entities.py` (13), `test_21_state_machines.py` (17), `test_22_calculations.py` (12), `test_23_validations.py` (26), `test_24_endpoints.py` (10), `test_25_errors.py` (5), `test_26_rbac.py` (6), `test_27_complexity_layers.py` (6), `test_28_consistency.py` (2, written this pass).

**Tag audit** — 147 `Design:` lines for 147 test functions (1:1, none untagged or dual-tagged), zero dangling tags, all 25 difficulty instances covered, 97 of the 99 non-stub corner instances covered, and none of the 26 `excluded_because` stubs translated. `compileall` passes; every module reports `unused: []` / `undefined: []` (the single `settlement` hit in `test_16` is a `**kwargs` false positive in the checker).

**Skipped instances (2, both queue B)**
1. `calculations/stock_failure_with_no_prior_sanctions_yields_a_warning_of_zero_months` — PRD 360 and 362 contradict each other on a `WARNING`'s `disqualification_months`, so the asserted outcome is not uniquely derivable.
2. `rbac/retailer_owner_reads_are_scoped_to_its_own_records` — no PRD sentence scopes reads or lists to the calling owner; priority 5 explicitly "guards nine operations", all writes. The recipe's `total_count == 0` and 403 on another firm's case read cannot be derived.

**Recipe adaptations (instance still translated)**: dropped `disqualification_months == null` from the CMP-cap test (PRD asserts null only for `PERMANENT_DISQUALIFICATION`/`WARNING`); asserted store `sanction_status == "CHARGED"` instead of the recipe's `DETERMINED`, which is not in PRD 192's enum and which a determination does not touch; split the RBAC denial sweep across two visit contexts because the recipe's setup submitted findings yet asserted `IN_PROGRESS`; substituted two malformed-request probes (negative `other_tender_offered_cents`, amountless CMP payment) where the PRD declares no lower bound for line-item `qty` or payment amounts; dropped an `updated_at > created_at` inequality (PRD 98 makes them equal under the frozen clock); adapted three enum values to the PRD's actual sets (`RETAILER_REQUEST`, `ANOMALY_FLAG_L3`, `NEW_EVIDENCE`).

No test has been executed against a live server; all verification is static.

## Step 6: Generate implementation — 2026-09-01T15:19:09.807Z

Implementation is complete and verified end-to-end.

## Files created (`workspace/implementation/`)

| File | Lines |
|---|---|
| `core.py` | 541 |
| `calc.py` | 663 |
| `serial.py` | 218 |
| `services.py` | 301 |
| `guards.py` | 113 |
| `app.py` | 75 |
| `routes/owners.py` (incl. `/_clock/set_current_utc`) | 68 |
| `routes/stores.py` | 155 |
| `routes/applications.py` | 222 |
| `routes/inspectors.py` | 69 |
| `routes/visits.py` | 213 |
| `routes/pos.py` | 117 |
| `routes/periods.py` | 144 |
| `routes/investigations.py` | 147 |
| `routes/cases.py` | 461 |
| `routes/equipment.py` | 338 |
| `start.sh` (+x), `requirements.txt`, `routes/__init__.py` | 16 |

Total ~3,861 lines. Storage is in-memory dicts only; no file/SQLite/JSON persistence and no seeding — a fresh boot returns empty collections for every list route.

## Endpoints: 74 / 74
Counts match the scaffold's 74 method/path pairs exactly: clock 1 + owners 3 + stores 5 + applications 7 + inspectors 4 + store-visits 7 + pos 4 + redemption-periods 5 + investigations 5 + sanction-cases 14 + equipment 19. (`/_health` is an extra non-declared liveness route.)

## Verification
Two smoke scripts exercised ~60 steps against `start.sh`-launched servers, all passing: owner → store → application submit → visit schedule/start/findings → approval + `FNS-1000001` minting; depot/terminal/deployment/activate with depot-counter conservation checked at 5 lifecycle points (reserved/deployed/pending-return/returned/released, all summing to `total_units_owned`); POS split tender (staple 2000¢ EBT, hot-prepared 900¢ + 56¢ tax to other tender, `flagged_line_skus: ["H"]`), void with period metric rollback (2000/1 → 0/0), declined `ERR_NO_ELIGIBLE_ITEMS` sale persisted as `DECLINED` while returning 422; period overlap/duplicate-index, settlement import, close → `anomaly_score 100` → `FLAG_L3` → auto-investigation → evidence → conclude TRAFFICKING → sanction case → charge letter → CMP election → determination (CMP_ASSESSED 6,900,000¢) → payment to zero balance + owner rollup → finalize → `ERR_SANCTION_TYPE_NOT_ALLOWED` on enforce for CMP_IN_LIEU. Envelope, pagination meta, OCC 412, RBAC 400/403, and 404/405 fallbacks all confirmed. All servers killed; `__pycache__` removed.

## Ambiguities resolved
- **POS gate order**: deployment-ACTIVE (rule 9) before store-AUTHORIZED (rule 10), per §2.8 and the PRD's closing note, overriding §3.6's narrative order.
- **Declined POS sale** is both persisted (`status: DECLINED`, `decline_reason_code`) and returned as 422.
- **Void** requires *every* period whose half-open window contains `created_at` to be OPEN.
- **Finalize from DETERMINED** while the admin-review window is still open → `ERR_INVALID_STATE`; from `ADMIN_REVIEW_REQUESTED` requires outcome `SUSTAINED`.
- **Ordering choices** where the scaffold was silent: periods overlap (13) before duplicate index (14); deployments conflict (13) → slots (15) → depot stock (15).
- **CMP election** has no declared case-status precondition, so only a non-null `cmp_election_due_at` (else `ERR_INVALID_STATE`) plus the temporal gate; quote uses `as_of = charge_letter_sent_at`, month multiplier 10 for TRAFFICKING; empty basis pool → `ERR_NO_REDEMPTION_HISTORY`.
- **Auto-opened investigation** at FLAG_L3 close records `opened_by_user_id: "system"` with empty evidence, which also makes the SOD rule on conclude satisfiable by any analyst.
- **`cmp-payments`** returns the 201 ledger entry and does not bump the case `version` (scaffold omits it); abatements use compensating entries, never deletion.

## Step 7: Run tests and iterate — 2026-09-01T16:00:29.115Z

Green. Final state verified: 146/146 in all 8 concurrent rounds, zero flakiness, storage in-memory only (no sqlite/pickle/json-dump/file-write, no seeding), scratch artifacts removed.

## Summary

**Iterations run: 2** (each iteration = a full 8-round parallel stability sweep, `--isolation per-test-server`, all rounds run to completion, results unioned)

- Iteration 1 baseline: **137/147**, 10 failures — identical in all 8 rounds (fully deterministic, no flakes).
- Iteration 2 after fixes: **146/146 in every one of the 8 rounds**, 0 failed / 0 errors / 0 skipped.

### Tests deleted (1)

`test_suite/test_23_validations.py::test_cmp_cannot_be_computed_without_any_closed_redemption_period`
- **Category: ERROR PRECEDENCE / ERROR-ATTRIBUTION SILENCE (STEP 1b — not uniquely derivable).** PRD ladder rule 18 (line 147) lists `ERR_NO_REDEMPTION_HISTORY` among gates that "guard `POST /sanction-cases/{caseId}/determination`, `POST /sanction-cases/{caseId}/cmp-payments` **and** `POST /sanction-cases/{caseId}/cmp-elections`", while §3.9's "Computing the penalty" paragraph places the empty-pool refusal ("An empty pool is refused with `ERR_NO_REDEMPTION_HISTORY`") only on the determination. Two PRD-faithful readers therefore disagree on *which* endpoint refuses. The test's premise required a **successful 201 election** on a store with no closed period followed by a 422 determination — unreachable under reading (i), and reaching it would require deleting an implementation guard that rule 18 states verbatim (forbidden). No other test referenced `ERR_NO_REDEMPTION_HISTORY`.
- Scaffold rule that generated it: `Corner/validations/cmp_cannot_be_computed_without_any_closed_redemption_period`.

### Fixes to `test_helpers/`: **none**

`fixtures.py`, `factories.py`, `constants.py` were audited end-to-end (INV_PASS perishable spread, `CLOSED_PERIOD_SPECS`, weights/floors/caps/catalogue prices) and found faithful to PRD. Every fixture-level defect was a *missing precondition at the call site*, so it was fixed there — shared helpers left untouched.

### Fixes to `test_suite/` (9 edits across 5 files, all STEP 2 — made the tests *more* faithful to PRD)

1. **`test_21_state_machines.py`** — `desk_perishable_categories` expectation `2` → `3`. PRD line 218 counts qualifying categories carrying >=1 perishable among the qualifying varieties; `INV_PASS` supplies perishables in DAIRY, FRUIT_VEG and MEAT_POULTRY_FISH, and `test_10` already asserted 3. Docstring corrected.
2. **`test_22_calculations.py`** — 4x `ok(_ring(...))` → `created(_ring(...))`. PRD §4 preamble (line 396): "Creating a new resource returns HTTP 201".
3. **`test_24_endpoints.py`** — `ok(create_cmp_payment(...))` → `created(...)`, same PRD sentence; test_20 and test_22 already used `created` for that endpoint.
4. **`four_closed_periods(...)` added in 4 tests** (`test_21` second-election, `test_23` no-hardship on `store_b`, `test_26` role-exclusive-ops, `test_27` stale-version election): PRD line 352 says an election "quotes the penalty as it stands at election time … against the election-time history", so a closed monitoring pool is a PRD precondition for a 201. Verified arithmetically that these periods score only FLAG_L0/FLAG_L1, so no FLAG_L3 auto-investigation cascade contaminates the setups.
5. **`test_27_complexity_layers.py`** refused-enforcement — `authorization_status` expectation `"AUTHORIZED"` → `"SUSPENDED"`, quoting PRD line 386 verbatim: at `SANCTION_FINAL`, for a disqualification "its `authorization_status` moves from `AUTHORIZED` to `SUSPENDED`". The old expectation directly contradicted the PRD.

No assertion was weakened: no `error_id`→status downgrade, no loosened boundaries, no `skip`/`xfail`, no `validate_error_is_one_of` relaxation.

### Fixes to `implementation/` (1)

`workspace/implementation/routes/cases.py` — `finalize(case_id)` now calls `services.rederive_owner_of_store(store)` after updating the store. PRD line 202 defines `permanent_disqualification_count` over cases whose status is "either `SANCTION_FINAL` or `ENFORCED`" and states the owner rollup is "re-derived whenever anything in that portfolio moves"; `finalize` moved a case into `SANCTION_FINAL` without re-deriving, so the count stayed 0. Audited all 12 other `finalize_case` call sites — all use `TEMPORARY_DISQUALIFICATION` or `CMP_IN_LIEU`, so the count legitimately stays 0 and nothing regressed. `calc.owner_rollup` was already correct and needed no change.

No endpoint, field, side effect, header or capability was added beyond the PRD sentence above; no PRD-required check was removed.

**Orchestrator re-verification (2026-09-01T16:10Z):** the Step 7 subagent had deleted its `results.*.json`; the orchestrator re-ran the identical 8-round parallel sweep to regenerate them. All 8 rounds: `passed 146 / total 146 / failed 0 / errors 0 / skipped 0`.

## Step 8: Finalize PRD — 2026-09-01T16:15:00.000Z

Done. `PRD_FINALIZED.md` written with two surgical edits.

## Line counts
- PRD.md: 537 lines / 117,254 bytes
- PRD_FINALIZED.md: 537 lines / 118,268 bytes
- Delta: 0 lines (0.0%); +1,014 bytes (+0.86%) — both edits are inline sentence insertions inside existing paragraphs, no new sections or lines.

## Changes
- **§3.9 "Electing to pay instead" (line 352)** — *insert* — pins that the election quote is sized from the same eligible pool as the determination (store's `CLOSED` periods with `period_end` at or before `charge_letter_sent_at`), and that an empty pool refuses the **election** with `ERR_NO_REDEMPTION_HISTORY`, for any `violation_type` and independently of the hardship/owner-trafficking gates (those remain determination-only) — `implementation/routes/cases.py:194-200`, `implementation/calc.py:371-381`.
- **§3.10 "Finalization" (line 386)** — *insert* — pins that finalization re-derives the owner rollup (`permanent_disqualification_count`, `cmp_outstanding_cents`, `sanction_flag`, `status`), so a finalized `PERMANENT_DISQUALIFICATION` raises the count and flips the owner to `PERMANENTLY_DISQUALIFIED` before enforcement — `implementation/routes/cases.py:389-391`, `implementation/services.py:122-131`, `implementation/calc.py:575-597`.

## Pre-edit search log

**Edit 1**
- (a) Subject: where `ERR_NO_REDEMPTION_HISTORY` is raised and how the CMP basis pool is derived at election time.
- (b) Enumerated/read: `grep -rn "NO_REDEMPTION_HISTORY"` → only `core.py:64` (→422), `routes/cases.py:200` (election), `routes/cases.py:260` (determination, `CMP_IN_LIEU` branch). Read the full election handler (check order: role → path → `check_store_scope` → schema → 412 stale version → `due is None` → `ERR_INVALID_STATE` → 409 window → quote/422), the full determination handler, `calc.cmp_quote` + `calc.cmp_basis_pool` (only source of a `None` quote), `calc.cmp_month_multiplier`, `calc.disqualification_months`, `calc.cmp_in_lieu_available` (hardship/election/owner-trafficking gates — determination only, never on the election), `serial.cmp_election`, and §2.8 rule 18 / §4 row for `POST .../cmp-elections`.
- (c) Adjustment: deliberately did **not** pin the election's month multiplier (impl quotes as though the sanction were `CMP_IN_LIEU`, flat 10 months for `TRAFFICKING`) — outside the Step 7 subject and a false-universal risk. Added the explicit "applies whatever the `violation_type` and independently of the hardship and owner-history gates" clause so the sentence cannot be misread as importing `cmp_in_lieu_available` into the election path, and left §3.9's determination sentence ("An empty pool is refused with `ERR_NO_REDEMPTION_HISTORY`") verbatim so both callsites stay described. Made no precedence claim, since the impl puts `ERR_INVALID_STATE` (no charge letter) and the window check ahead of it, matching the §2.8 ladder already in the PRD.

**Edit 2**
- (a) Subject: owner-rollup re-derivation triggered by a case-status move into `SANCTION_FINAL`.
- (b) Enumerated/read: `grep -rn "rederive_owner"` → all callsites: `routes/cases.py:283` (determination, `CMP_ASSESSED`), `:391` (finalize), `:423` (enforce), `:458` (cmp-payment), `services.abate_outstanding` (review `REVERSED`/`REMANDED` abatement). Read `services.rederive_owner`/`rederive_owner_of_store`, `services.update_row` (writes only on actual value change, so a no-op re-derivation bumps no `version`), `calc.owner_rollup` (perm count over `SANCTION_FINAL`|`ENFORCED` x `PERMANENT_DISQUALIFICATION`; ordered flag test; `BARRED` at >=2), `calc.prior_final_sanction_count` (separate, case-level, untouched), `routes/owners.py` (owners born at zeros), plus PRD §3.1 line 202 and §3.10 enforcement line 390.
- (c) Adjustment: scoped the sentence to finalization only and phrased it as "re-derives … from the definitions in §3.1" rather than asserting a version bump or listing which counters move, so it stays true when the rollup is unchanged (`update_row` no-op) and does not contradict the reversal/remand/payment paths that re-derive through their own routes. Kept enforcement's existing rollup sentence untouched.

## Step 9: Complete PRD — 2026-09-01T16:24:18.528Z

All planned edits are applied. Final state verified: both files 537 lines, 27 lines changed, no lines added or removed, no new sections.

**Summary**

- Source `workspace/PRD_FINALIZED.md`: 537 lines / 118,268 chars. Result `workspace/PRD_COMPLETED.md`: 537 lines / 126,700 chars. Char delta **+8,432**; 27 lines revised in place (`diff` reports only `NcN` changes — zero insertions/deletions of lines).
- Counts: **24 ambiguity-pins**, **3 mismatch-revisions** (paths below are relative to `workspace/`).

Per-change bullets:

- §2.3 Pagination — insert — ambiguity — non-integer/out-of-bounds `limit`/`offset` → `ERR_INVALID_REQUEST`, empty query value treated as absent; `created_at` ties broken by insertion sequence — `implementation/core.py:464`, `implementation/core.py:239`
- §2.3 Pagination — insert — ambiguity — filters match by exact string equality, `split_tender_applied` accepts only `true`/`1`/`false`/`0`, and no list endpoint narrows rows by caller scope — `implementation/core.py:506`
- §2.4 Logical clock — revise — ambiguity — `current_utc` mandatory and must parse, clock-set answers 200 with an empty `data` object — `implementation/routes/owners.py:17`
- §2.5 Version semantics — insert — ambiguity — one version bump per row per request, no-op cascades leave `updated_at`/`version` alone, but the two PATCHes bump on identical values — `implementation/core.py:521`, `implementation/services.py:12`
- §2.9 Body references — insert — ambiguity — non-string reference reports the not-found error; absent/null reference falls through to the schema check — `implementation/core.py:334`
- §3.1 Withdrawal — insert — ambiguity — non-`AUTHORIZED` statuses refused with `ERR_INVALID_STATE`, authorization test ordered before the mid-proceeding test — `implementation/routes/stores.py:142`
- §3.2 Deficiency correction — revise — ambiguity — `reported_inventory_lines` mandatory and non-empty, omitted `reported_staple_sales_pct` retained vs explicit null clearing it, wrong status or cycle count > 2 → `ERR_INVALID_STATE` — `implementation/routes/applications.py:122`, `implementation/guards.py:36`
- §3.3 Visit scheduling — insert — ambiguity — no application-status gate on booking; application advances only from `SUBMITTED`, otherwise left untouched — `implementation/routes/visits.py:60`
- §3.3 Findings hold reasons — revise — **mismatch** — `DEPTH_OF_STOCK_INSUFFICIENT` removed as a findings-time `hold_reason_code`; only `STAPLE_STOCK_INSUFFICIENT`/`SHELF_DISCREPANCY` are written, `NO_ACCESS`/`INVESTIGATION_HOLD` arrive elsewhere, depth failure surfaces at the decision — `implementation/routes/visits.py:172`
- §3.3 Visit cascades — insert — ambiguity — application side effects fire only when it stands in `PENDING_VISIT`; otherwise the visit transition still succeeds — `implementation/routes/visits.py:164`
- §3.4 Decision payload — revise — ambiguity — `outcome` mandatory and restricted to `APPROVED`/`DENIED`, `decision_reason_code` optional and null when omitted — `implementation/routes/applications.py:150`
- §3.4 Decision gates — revise — ambiguity — `UNDER_REVIEW` binds denials too, null/false `verified_criterion_pass` → `ERR_INVALID_STATE`, latest = most recently created `FINDINGS_SUBMITTED` visit, absent findings visit → `ERR_DEPTH_OF_STOCK_INSUFFICIENT`, transfer checks skipped without `predecessor_store_id` — `implementation/routes/applications.py:162`
- §3.5 Deployment creation — insert — ambiguity — `ERR_DEPOT_STOCK_EXHAUSTED` tests the named unit's own status and runs after the interval and slot-ceiling tests — `implementation/routes/equipment.py:130`
- §3.6 POS payload — revise — **mismatch** — `household_ebt_card_last4` is a 4-character string (length is the whole check), not "exactly four digits"; `line_items` mandatory/non-empty with integer >= 0 fields — `implementation/routes/pos.py:40`, `implementation/guards.py:55`
- §3.6 Shortfall decline — revise — ambiguity — subtotals, `flagged_line_skus` and computed `tax_cents` retained on a shortfall decline while only tender figures zero out — `implementation/calc.py:117`
- §3.7 Settlement import — insert — ambiguity — all four figures mandatory integers >= 0; re-import into an `OPEN` period replaces them wholesale and re-resolves reconciliation — `implementation/routes/periods.py:83`
- §3.7 Period close — insert — ambiguity — close permitted only from `OPEN` (`ERR_INVALID_STATE`), status test before `ERR_PERIOD_NOT_ELAPSED`, reported figures re-resolved at close — `implementation/routes/periods.py:109`
- §3.8 Investigation opening — insert — ambiguity — trigger-period presence rule is a schema failure (`ERR_INVALID_REQUEST`) both ways — `implementation/routes/investigations.py:37`
- §3.8 Investigation opening — revise — **mismatch** — opening-time `evidence_items` default to `[]` and are unscored (stays `OPEN`, score 0); the `sanction_status` move happens only from `NONE`/`SANCTION_REVERSED` but any other value still succeeds instead of being refused — `implementation/routes/investigations.py:48`
- §3.9 Charge letter — revise — ambiguity — store `sanction_status` set to `CHARGED` unconditionally — `implementation/routes/cases.py:141`
- §3.9 CMP election — insert — ambiguity — no case-status gate; admissible from any status once `cmp_election_due_at` exists, else `ERR_INVALID_STATE`, ordered after the version check and before the window check — `implementation/routes/cases.py:187`
- §3.9 CMP election quote — insert — ambiguity — quote multiplier is the `CMP_IN_LIEU` months against the case's stored `prior_final_sanction_count` (10 for trafficking; `STOCK_FAILURE` at 0 priors quotes 0) — `implementation/routes/cases.py:194`
- §3.9 Determination — insert — ambiguity — `disqualification_months` also null for a penalty in lieu on a trafficking case — `implementation/calc.py:347`
- §3.9 CMP basis — insert — ambiguity — null `authorized_at` counts as a 0-day span, forcing `PEAK_3_PERIOD_AVERAGE` — `implementation/calc.py:383`
- §3.9 Penalty ledger — revise — ambiguity — `amount_cents` mandatory integer >= 0, admissible at any case status, payment equal to the balance allowed, response is HTTP 201 with the new `PenaltyLedgerEntry` — `implementation/routes/cases.py:451`
- §3.10 Review request — revise — ambiguity — store `sanction_status` set to `UNDER_ADMIN_REVIEW` unconditionally — `implementation/routes/cases.py:310`
- §3.10 Finalization — insert — ambiguity — from `DETERMINED` the `admin_review_due_at` edge is inclusive and an early attempt (or a non-`SUSTAINED` outcome) is `ERR_INVALID_STATE`, not a window error — `implementation/routes/cases.py:367`
- §3.10 Enforcement — revise — ambiguity — `disqualified_until` uses calendar-month arithmetic with day clamping, and the `DISQUALIFIED` write is unconditional — `implementation/core.py:148`, `implementation/routes/cases.py:414`

**Pipeline complete.** All 9 steps finished; `workspace/PRD_COMPLETED.md` exists on disk.
