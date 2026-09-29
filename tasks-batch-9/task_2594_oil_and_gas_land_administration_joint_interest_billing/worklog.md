# Worklog — task_2594_oil_and_gas_land_administration_joint_interest_billing

## Step 1: Create task directory — 2026-09-03T00:00:00.000Z

Created pre-assigned task directory `/home/ubuntu/github/CodingPRD/tasks/task_2594_oil_and_gas_land_administration_joint_interest_billing` and its `workspace/` subdirectory. Index 2594 was fixed by the scenario number (no ./tasks/ scan, no auto-allocation — other pipelines run concurrently on this host).

## Step 2: Generate scaffold artifacts (§1.0–§1.9) — 2026-09-03

Wrote the three scaffold files from the scenario text plus the scaffold-generator SKILL only (no
sibling task under `tasks/` was read):

- `SCAFFOLD.yaml` — 3410 lines; §1.0–§1.7 only (no design keys). 14 entities, 61 endpoints,
  12 state machines, 11 calculations, 88 validations, 83 errors, 5 roles, 2 concurrency rules.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 3448 lines; `scaffold_difficulty_design` with 9 §0.5 rule
  groups and 25 instances, all with full `test_recipe`s.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4327 lines; `scaffold_corner_design` with all 9
  claim-extraction-guide sections and 82 instances (58 recipes + 24 `excluded_because:` stubs).

Audit fixes made while deriving §1.9: added `ERR_STATEMENT_NOT_SETTLEABLE`,
`ERR_POOLING_NOT_FORMING`, `ERR_NO_OPERATOR_INTEREST` and a second `ERR_WELL_NOT_POOLED` row for
four previously unmapped state-machine preconditions; `JibStatement.statement_number` and
`Well.spud_date` re-declared `source: input`; the two JibLineItem sub-resource GETs re-templated to
`{id}` so FK reverse-reachability resolves. `scaffold_lint.py` reports `VERDICT: clean lint`.

## Step 2 (orchestrator record, subagent summary verbatim) — 2026-09-03T18:12:38.499Z

Scaffold 2594 is complete and lint-clean.

## Files

| Path | Lines |
|---|---|
| `.../SCAFFOLD.yaml` | 3410 |
| `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 3448 |
| `.../SCAFFOLD_CORNER_DESIGN.yaml` | 4327 |

`SCAFFOLD.yaml` holds only §1.0–§1.7 (top-level keys: scenario, domain_name, api_prefix, response_envelope, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles) — no `scaffold_difficulty_design` / `scaffold_corner_design` keys. Each design file has exactly one top-level key.

## Counts

- **SCAFFOLD.yaml**: 14 entities, 61 endpoints, 12 state machines, 11 calculations, 88 validations, 83 errors, 5 roles, 2 concurrency rules (target band for "harder than expert" met or exceeded on every axis).
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)**: 25 instances across all 9 §0.5 rules, every one with a full `test_recipe` — dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 3, priority_pair_validation_conflict 3, boundary_precision_check 4, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2.
- **SCAFFOLD_CORNER_DESIGN.yaml (§1.9)**: 82 instances across all 9 claim-extraction-guide sections — entities 14, state_machines 15, calculations 15, validations 8, endpoints 6, errors 12, rbac 6, cross_cutting_complexity_layers 5, consistency_model 1. 58 carry full `test_recipe`s; 24 are `excluded_because:` stubs citing a §1.8 instance (all resolve by name, all in `<rule_id> / <instance>` form). Zero duplicate names within or across the two design files.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    61
  §1.1 entities declared:     14
  §1.8 instances scanned:     25
  §1.9 instances scanned:     58
  Calls scanned (§1.8+§1.9):  1330

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Notable §1.5/§1.4 reshapes forced by the §1.9 audit

- Four state-machine preconditions had no error mapping: added `ERR_STATEMENT_NOT_SETTLEABLE` (409), `ERR_POOLING_NOT_FORMING` (409), `ERR_NO_OPERATOR_INTEREST` (409) and a second priority-50 `ERR_WELL_NOT_POOLED` row for the `PROPOSED -> DRILLING` guard (validations grew 84→88, errors 80→83).
- `JibStatement.statement_number` and `Well.spud_date` were declared `source: system` but accepted as endpoint input — re-declared `source: input` with derivation notes rather than dropping the inputs.
- Lint check (f) rejected both JibLineItem FKs because its sub-resource form requires a literal `{id}` parent placeholder; `GET /land-admin/jib-statements/{id}/line-items` and `GET /land-admin/interest-owners/{id}/jib-line-items` were re-templated accordingly (no endpoints added).
- Two §1.8 trigger calls used `as: ComplianceOfficer` on the LandAdministrator-only `status-changes` endpoint; corrected.
- Grounds resolvability sweep fixed stale references (`RevenueDisbursement` → `ProductionRevenue`/`OwnerDisbursement`, `JibStatement.consent_normalized_wi_pct` → `JibLineItem`, missing `.fields.`, a bare `validations[priority=60]`), and an assert citing a nonexistent `BILLED` cost status.

## Step 3: Copy shared files — 2026-09-03T18:12:50.000Z

Copied `INSTRUCTION.md` from the project root to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T18:31:55.412Z

Orchestrator truncation check (per pipeline instruction): `wc -l PRD.md` = 576; tail shows the §5 error
catalogue ending on a complete table row; §4 has 63 table lines (61 endpoints + header + separator) and
§5 has exactly 83 `ERR_` rows. Document ends at a real section boundary — NOT truncated, no regeneration
needed.

Subagent summary, verbatim:

PRD generation complete.

**Output:** `.../workspace/PRD.md` — **576 lines**, built in 12 chunked `cat >>` appends (never a single Write). Ends at a real boundary: the 83rd of 83 error-table rows, table complete, no truncation.

**Section list**
- 1. Introduction
- 2. Global Specifications & System-Wide Principles — 2.1 Role-Based Access Control · 2.2 API Response Structure (verbatim block) · 2.3 Pagination · 2.4 Record Identity, Audit Fields and the Logical Clock · 2.5 Request Evaluation Order (17-step ladder, priorities 10→75) · 2.6 Money, Acreage and Interest Precision · 2.7 Optimistic Concurrency on Wells and Statements · 2.8 The Joint Account Ledger and Its Invariants · 2.9 Cascade Discipline
- 3. Business Logic & Workflows — 3.1 Lease Inventory, Tenure and the Obligation Calendar · 3.2 Wells, Pooled Units and Allocation of Committed Acreage · 3.3 The Division of Interest: Owners, Positions and Bonding · 3.4 AFEs, Elections and Non-Consent · 3.5 Booking Joint-Account Costs and Preparing a Statement · 3.6 Issuing the Statement: Reallocation, Per-Owner Shares and the Bill · 3.7 Partner Audit Rights, the Dispute Exchange and the Fate of a Bill · 3.8 Revenue Distribution and Owner Disbursements · 3.9 Assignments, Preferential Purchase Rights and the Conveyance of Interest
- 4. Endpoint Definitions — 4-column table, **61 rows verified**
- 5. Error Code Catalogue — 2-column table, **83 rows verified**

**Coverage (machine-verified against the scaffold, not by eye)**
- 14/14 entities, 12/12 state machines, 11/11 calculations, 5/5 roles, 61/61 endpoints, 83/83 errors, 88 validations rendered as the §2.5 ladder plus their in-context prose.
- **Contract 1 (Field-Name Coverage): PASS** — 173 required identifiers extracted from `entities[].fields[].name` + all endpoint `input`/path params; diffed against every backticked token in the PRD: **0 missing**.
- **Contract 2 (Rule Coverage): PASS** — all 83 error IDs appear in explanatory prose in §1–§4 (not only in the §5 table): 0 missing. All state-machine states: 0 missing. All entity enum values: 0 missing. Both OCC rules, all multi-hop cascades (4-hop lease expiry, 4-hop partial-consent, 3-hop dispute adjustment, 4-hop revenue suspension), all `applies_to` scopes, field defaults, and both sibling-branch pairs written at equal density.
- **Contract 3 (§3 Path Purity): PASS** — 1294 backticked tokens (344 unique) scanned in §3: 0 leading-`/` tokens, 0 bare HTTP methods, 0 method+path combinations; `/land-admin` appears 0 times in §3.
- No pseudocode: scan for `==`, `!=`, `>=`, `<=`, `+=`, `-=`, `min(`, `max(`, `round_half_up`, `IN {` and fuzzy quantifiers returns clean outside the verbatim §2.2 block.

**Hard constraints honored:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced; no sibling task directory was read.

**Scaffold inconsistencies reconciled in prose (worth knowing for the implementer):** issuance adds `non_consent_withheld_cents + penalty_accrued_cents` to the recoverable balance (endpoint wording, consistent with the revision/void reversal) rather than the state machine's penalty-only phrasing; `WellInterest` boundary dates at closing are stated as the supplied `closing_date` (the transfer machine's wording) rather than "logical clock date"; the PLUGGED transition names `ComplianceOfficer` as actor while the endpoint's `roles` is `[LandAdministrator]`, so §3.2 asserts no actor and §4 uses the declared roles; lease list is documented as the one `created_at` descending exception to the ascending default; constraints with no declared error ID (AFE-number uniqueness, three uncoded path identifiers, the issuance `activity_class`↔`well_status` match) are stated as rules without inventing error codes.

## Step 5: Generate unit tests — 2026-09-03T19:50:21.566Z

ORCHESTRATOR DEVIATION NOTED (autonomy decision, recorded rather than escalated): the skill requires
Steps 5 and 6 to be launched in a SINGLE assistant message so that the implementation generator is
*physically* unable to read `test_suite/` (it does not exist yet at its spawn time). I launched Step 5
alone, so that physical isolation was lost. Compensating control applied instead of restarting the
pipeline: the Step 6 prompt carried an ABSOLUTE PROHIBITION naming both `test_suite/` and
`test_helpers/` explicitly and forbidding any read/list/glob/grep of them, plus the two design YAMLs.
Verified after the fact: `test_helpers/` and `test_suite/` sit at the task root (not under
`workspace/`), and `workspace/` contained only INSTRUCTION.md and PRD.md when Step 6 began.

Subagent summary, verbatim:

Both output directories are complete and verified.

## Files written

`test_helpers/` (Stage 1, 2,870 lines)
`__init__.py` 55 · `api_client.py` 332 · `api_errors.py` 180 · `assertions.py` 447 · `constants.py` 88 · `factories.py` 397 · `fixtures.py` 802 · `test_users.py` 95 · `types.py` 474

`test_suite/` (Stage 2, 4,600 lines, 81 tests)
`conftest.py` 50 · `test_01_cost_basis_and_late_interest_variants.py` 137 (2) · `test_02_billing_formula_composition.py` 175 (3) · `test_03_parallel_and_cyclic_lifecycles.py` 149 (2) · `test_04_multi_hop_cascades.py` 246 (3) · `test_05_check_precedence_pairs.py` 179 (3) · `test_06_inclusive_boundaries.py` 326 (4) · `test_07_cross_entity_preconditions.py` 261 (3) · `test_08_interval_conventions.py` 184 (2) · `test_09_conserved_quantities.py` 209 (2) · `test_10_lease_and_well_records.py` 271 (7) · `test_11_record_shapes_and_relationships.py` 298 (7) · `test_12_lifecycle_transitions.py` 391 (9) · `test_13_derived_amounts.py` 244 (5) · `test_14_write_guards.py` 311 (6) · `test_15_endpoint_contracts.py` 290 (6) · `test_16_error_surface.py` 427 (8) · `test_17_role_boundaries.py` 205 (5) · `test_18_concurrency_and_consistency.py` 247 (4)

## Instance accounting

- **Queue A (§1.8 difficulty)** — 25 non-stub instances → **24 tests**, 1 skipped.
- **Queue B (§1.9 corner)** — 58 non-stub instances → **57 tests**, 1 skipped. By section: entities 14, state_machines 9, calculations 5, validations 6, endpoints 6, errors 8 of 9, rbac 5, cross_cutting_complexity_layers 3, consistency_model 1. The 24 stub instances were not translated.
- **Total: 81 tests**, each carrying exactly one `Design:` tag; all 81 tags are distinct and every one resolves to a real instance name in its source yaml.

## Skips (2), grouped by reason

**PRD does not uniquely derive the asserted outcome (2)**
1. `Difficulty/non_linear_state_machine/assignment_fork_ppr_exercise_versus_waiver_pays_a_different_grantee` — the recipe requires the first closing to succeed on the `PPR_EXERCISED` arm while `ppr_waiver_count` is 0, `ppr_eligible_count` is 1 and the clock sits inside the notice window. PRD §3.9 requires the window to be genuinely shut (all holders waived, or clock strictly past `ppr_deadline_date`), otherwise `ERR_PPR_WINDOW_OPEN` (422).
2. `Corner/errors/a_third_shut_in_payment_on_the_same_lease_is_rejected` — the premise state (`shut_in_payments_made == 2`) is built by recording two `SHUT_IN_PAYMENT` events on a lease with no allocation to any well and no `SHUT_IN` well, but PRD §3.1 admits a `SHUT_IN_PAYMENT` "only while at least one of the lease's committed acreage allocations feeds a well whose operational status is `SHUT_IN`", so the premise is unreachable and `ERR_SHUT_IN_LIMIT_EXCEEDED` is not derivable.

## Verification performed

- `python3 -m py_compile` clean on every emitted file; `pytest test_suite --collect-only` → **81 tests collected**, no import or collection errors.
- Every citation line in every docstring was checked as a literal substring of `workspace/PRD.md` — **0 misses**.
- Exactly one `Design:` line per test, always the last non-empty docstring line — **0 violations**; no tag points at a non-existent or stub instance.
- No occurrence of the word "scaffold" anywhere in the emitted code.
- `workspace/` still contains only `INSTRUCTION.md` and `PRD.md`; nothing was written there and `workspace/implementation/` was never read or created.

## Two design-vs-PRD conflicts resolved in the PRD's favour (tests emitted, assertions tightened to what the PRD derives)

- `Corner/entities/list_leases_returns_a_paginated_envelope_with_total_count` — the recipe expected `L-003` on the second page, but PRD §2.3 makes the lease inventory the one listing ordered `created_at` **descending**, so the test asserts `["L-003", "L-002"]` on page one and the envelope fields on both pages.
- `Corner/entities/the_lease_well_allocation_junction_is_discoverable_from_both_sides` — the recipe asserted both of lease 1's allocations at factor `1.000000`, which contradicts its own well-side assertion; PRD §3.2 derives `0.750000` for the 480-acre row on the two-tract unit and `1.000000` for the sole row on the second well.

## Step 6: Generate implementation — 2026-09-03T20:27:18.547Z

Subagent summary, verbatim:

Implementation complete and verified.

## Files (`workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `start.sh` | 8 | bash launcher, guarded `pip install`, `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 57 | blueprint registration (`/land-admin` prefix + unprefixed `/_clock`), error handlers, `0.0.0.0:$PORT` (default 10000) |
| `common.py` | 233 | Decimal helpers (`ROUND_HALF_UP`, never `float`/`round()`), date math, logical clock (epoch `2026-08-01T00:00:00Z`, monotonic), envelope (`meta`/`response_type`/`data`, `req_`+20 alnum, 3-digit ms), `touch()` (once-per-request version bump) |
| `errors.py` | 99 | all **83** catalogued error IDs → HTTP status (incl. 402 bond/bonus, 412 stale-version, 403 `ERR_PPR_HOLDER_INVALID`, 409 `ERR_SUSPENSE_BALANCE_NONZERO`) |
| `store.py` | 230 | in-memory dicts only, 14 tables, empty at boot, per-entity field lists (JibLineItem = `id`+`created_at` only) |
| `validate.py` | 280 | auth/RBAC (5 roles, entity-backed `PartnerRepresentative`), field-shape validators, pagination (10/1..100, offset>=0) |
| `calc.py` | 516 | lookups, terminal guards, the 11 calculations, bond coverage (round-per-well then x1.25), overhead (round-before-clamp), cascades (4-hop lease expiry) |
| `jib_engine.py` | 184 | draft creation, revision numbering, issuance: non-consent reallocation, consent-normalized weights, signed residual, 3 independently-rounded buckets |
| `routes_lease/well/owner/afe/cost/jib/dispute/revenue/transfer/system.py` | 191/254/246/277/84/214/241/299/272/248 | the endpoint surface |

Total 3,934 lines. No SQLite/JSON/tmp persistence, no seeding (store empty at import; verified by grep).

## Coverage
**61 route rules** registered (matches the PRD's 61-endpoint table), 12 state machines, the 17-rung §2.5 ladder, 88 validations, 83 error codes, 5 roles.

## Boot smoke (port 18594-18601, each PID killed individually by port lookup — no broad pkill)
- Boots clean from a fresh process in <2 s; envelope, pagination meta, `401/403/400/404/412/402/409/422` paths all correct.
- Two end-to-end scripts drove the full system through the API: pooling -> interests with OCC (`ERR_STALE_WELL_VERSION`) -> AFE elections/closure (`PARTIALLY_CONSENTED`) -> cost entries -> draft/issue statement (line-item sum == statement total) -> dispute rebuttal/escalation/resolution -> revenue release (`tax + royalty + disbursed == gross` exactly) -> partner-scoped disbursement listing (`ERR_OWNER_MISMATCH`) -> payment with both interest bases (forced `FROM_PROCEEDS_RECEIPT` = 3881c on 5,902,508c x 6% x 4/365) -> suspense release -> PPR waiver **and** exercise branches, closing conserving WI = 1.000000 and NRI unchanged -> lease expiry cascade via obligation run (`allocations_withdrawn`, `leases_expired`, well -> `POOLED_TERMINATED`) -> second run at the same clock is a no-op (idempotent). Zero 5xx.

## Fidelity decisions worth flagging (PRD gaps)
- Undeclared 404s for `allocation_id`/`cost_entry_id`/`election_id` reuse the parent's declared code; undeclared gaps mapped to the least-bad catalogued code (`settled_on`/`event_date` in the future -> `ERR_EFFECTIVE_DATE_OUT_OF_RANGE`; non-suspended suspense-release -> `ERR_DISBURSEMENT_NOT_PAYABLE`; issuance activity-class mismatch -> `ERR_WELL_INVALID_STATUS`).
- Uniqueness on `well_name`/`afe_number`/`statement_number` is **not** enforced (no declared error code; only PRD-stated uniqueness rules are).
- Per PRD prose, `bond_check_required_cents` is recomputed on `WAIVE` only (not on `EXERCISE`); on a partial conveyance the assignor's replacement row carries its `non_consent_recoverable_balance_cents` forward ("runs with the interest").

## Step 7: Run tests and iterate to green — 2026-09-03T21:05:00.000Z

Orchestrator verification (per the "Verify Step 7 sweep artifacts" lesson): independently re-read all
eight `workspace/implementation/results.{1..8}.json` (timestamped 20:58, ~25.9 KB each) — every round
reports passed 81 / total 81 / failed 0 / errors 0. The clean sweep is real, not a subagent claim.

Subagent summary, verbatim:

Clean sweep: all 8 parallel rounds report `passed == total == 81`, `failed 0`, `errors 0`.

## Summary

**Iterations run:** 3 full 8-round parallel sweeps (9/81 -> 74/81 -> **81/81 x 8 rounds**).

**Tests deleted (PRD silence):**
- No whole test was deleted.
- One assertion removed under COMPUTED-FIELD/RESPONSE-FIELD SILENCE: `assert statement["settled_on"] is None` in `test_suite/test_15_endpoint_contracts.py` (`test_cash_cannot_be_applied_to_a_bill_that_is_still_being_contested`). PRD §3.7 mentions `settled_on` only as a settlement *request* field ("A `JointInterestAccountant` settles a statement by supplying `settled_on`, which must be on or before the logical clock's date."); it is never declared a persisted or returned statement field, so satisfying the assertion would have required adding an untraceable response field. The test's PRD-covered core (`ERR_STATEMENT_NOT_SETTLEABLE`, `statement_status == "DISPUTED"`, dispute still OPEN, `billed_to_date_cents`) was kept.

**Fixes applied to `test_helpers/`** (all in `test_helpers/fixtures.py`):
- `CLOCK_DEFAULT`: `"2026-07-10T00:00:00Z"` -> `"2026-08-10T00:00:00Z"` — the PRD fixes the logical clock's start at `2026-08-01T00:00:00Z` and it only moves forward, so every fixture that set a July clock got `ERR_CLOCK_MOVED_BACKWARD` (root cause of 70 of the original 72 failures). `test_helpers/constants.py` already encoded `CLOCK_START_UTC = "2026-08-01T00:00:00Z"`, confirming the July default was the bug.
- `setup_closed_non_consent_afe`: `election_deadline_date` `"2026-07-31"` -> `"2026-08-31"` — the deadline has to sit at or after the new clock date for the election window to be open.
- The explanatory comment above `CLOCK_DEFAULT` was rewritten to state why 2026-08-10 is the correct anchor (after the service epoch, after the June cost history, before the September primary-term deadline).
- The same +31-day July->August remap plus its derived date expectations was propagated through `test_suite/test_01` ... `test_18` (module `CLOCK` constants, AFE `election_deadline_date`s, later `set_clock` calls, and the dependent `response_due_date` / `rebuttal_due_date` / `payment_due_date` / `shut_in_*` / `first_production_date` / `filed_at` / `evaluated_at` literals).

**Other test-layer corrections (all PRD-traced, implementation left untouched):**
- `bond_check_amount_cents` -> `bond_check_required_cents` and `total_line_cents` -> `total_billed_cents` in test_09 — the PRD names those fields as used by the implementation.
- Obligation-event and dispute-exchange calls: expected `201` -> `200` (test_03 x3, test_12 x1, test_03 shut-in events x2). PRD §4: "A successful call that creates a new resource returns status code 201; every other successful call returns 200." Neither operation creates a resource — both mutate and return the lease/dispute.
- `filed_at` / `evaluated_at` literals given three fractional digits (`...T00:00:00.000Z`) per PRD §2.2/§2.3.
- test_16 empty-period draft: `total_billed_cents == 0` -> `== 25_000` (plus explicit `overhead_cents == 25_000`, `direct_cost_cents == 0`) — PRD §3.5 clamps overhead to a $250 floor "under both modes", unconditionally.
- test_16 duplicate-allocation case restructured: the fixture was issuing the duplicate commitment against an already-`POOLED_EFFECTIVE` well, so per the §2.5 ladder the rung-12 pooling-state guard (`ERR_POOLING_NOT_FORMING`) legitimately preempted the rung-16 uniqueness check. The test now creates a second well (`42-123-99999`), commits 40 of lease 1's 160 remaining acres to put it in `POOLED_FORMING`, then re-commits the same lease to get `ERR_DUPLICATE_ALLOCATION`; `well_meta["total_count"]` adjusted `1` -> `2`, which still proves the duplicate-API-number well was refused.

**Fixes applied to `implementation/`:** none. Every one of the 72 + 7 failures traced to a test-layer defect; the implementation was PRD-faithful in each case (clock epoch in `common.py`, 200-returning `record_obligation_event` in `routes_lease.py` and `record_exchange` in `routes_dispute.py`, non-persisted `settled_on` in `routes_jib.py`, rung ordering in `routes_well.py:commit_acreage`, unconditional overhead clamp in `calc.py`).

## Step 8: Finalize PRD — 2026-09-03T21:09:53.317Z

Step 8 was NOT skipped: although Step 7 applied 0 `implementation/` fixes, it did apply `test_helpers/`
fixes, `test_suite/` fixes and removed one assertion, so the skip condition (all four categories zero)
was not met. Orchestrator verification: `PRD_FINALIZED.md` is 576 lines / 129,971 bytes vs PRD.md's
576 lines / 128,200 bytes and `cmp` confirms the two files differ — the finalizer really edited.

Subagent summary, verbatim:

`workspace/PRD_FINALIZED.md` is written.

## Size delta
- PRD.md: 576 lines / 128,200 bytes
- PRD_FINALIZED.md: 576 lines / 129,971 bytes
- Line delta: 0 (+0.0%) — every edit is an inline sentence added inside an existing paragraph. Byte delta +1,771 (+1.38%).

## Changes (5 edits)

- **§2.4** — insert — pinned that every non-`created_at`/`updated_at` *instant* the service records or reports (`issued_at`, `submitted_at`, `elections_closed_at`, `filed_at`, `operator_responded_at`, `released_at`, `paid_at`, `evaluated_at`) is ISO 8601 UTC with exactly three fractional digits, and that calendar-date fields render as plain `YYYY-MM-DD` — `common.py:90` (`fmt_ts`), `common.py:180-184` (`json_value`).
- **§3.1 (maintenance events)** — insert — an obligation event is not a persisted resource; the call returns 200 with the updated lease, not 201 — `routes_lease.py:190`.
- **§3.2 (committing acreage)** — insert — the well's pooling-state guard (`ERR_POOLING_NOT_FORMING`, admitting only `UNPOOLED`/`POOLED_FORMING`) precedes the expiry/duplicate/acreage trio, with the body's `lease_id` still resolved first — `routes_well.py:112-121`.
- **§3.7 (exchange cycle)** — insert — a dispute exchange is not a persisted resource; the call returns 200 with the updated dispute, not 201 — `routes_dispute.py:178`.
- **§3.7 (settlement)** — insert — `settled_on` is a request-only field: required and validated, never stored on the statement and absent from the returned statement resource — `routes_jib.py:202-209`, `store.py:139-146` (`STATEMENT_FIELDS`).

## Per-edit pre-edit search log

1. **§2.4 timestamp format.** (a) Subject: rendering format of every timestamp field. (b) Enumerated: `common.py fmt_ts` (the only formatter), `common.py json_value` (all `datetime` -> `fmt_ts`, all `date` -> `isoformat`), `store.py serialize` + all 14 `out_*` field lists, `routes_afe.py:154,203,241` (`submitted_at`, `elections_closed_at`), `jib_engine.py:170` (`issued_at`), `routes_dispute.py:88,155` (`filed_at`, `operator_responded_at`), `routes_revenue.py:202,296` (`released_at`, `paid_at`), `routes_system.py:246` (`evaluated_at`), `routes_system.py:29` (clock echo). (c) Adjustment: scoped the claim to *instants* and added the explicit date-field contrast so the sentence cannot be read as forcing `payment_due_date`/`statutory_due_date`/`ppr_deadline_date` etc. into instant form; deliberately did not mention the clock endpoint's `current_utc` echo (out of scope).
2. **§3.1 obligation event 200.** (a) Subject: status code and persistence of a lease obligation event. (b) Enumerated: `routes_lease.py record_obligation_event` (all three `event_type` branches, returns `ok(lease_view(lease))` = 200), `store.py TABLES` (no events table), plus every `), 201)` site in the implementation (13 sites, none of them this endpoint). (c) Adjustment: attributed the code to "the rule of §4" rather than restating a general rule, so no other endpoint's status code is redefined.
3. **§3.2 pooling guard order.** (a) Subject: check order in acreage commitment / `ERR_POOLING_NOT_FORMING`. (b) Enumerated: `routes_well.py:101-137 commit_acreage` (get_well -> get_lease -> `guard_terminal(well)` -> pooling guard -> expiry -> duplicate -> acreage), the only other `ERR_POOLING_NOT_FORMING` site `routes_well.py:173 effectuate_pooling` (requires exactly `POOLED_FORMING`), `errors.py:40` (409), §2.5 rungs 7/11/12/13/16. (c) Adjustment: first draft said the guard fires "before the lease is examined at all", which contradicted `get_lease` running at rung 7 — revised to "before any of those three lease checks is reached (the body's `lease_id` is still resolved first, at rung 7)". Also enumerated `POOLED_EFFECTIVE`/`POOLED_TERMINATED` explicitly rather than writing "not forming", so the effectuation endpoint's stricter guard is untouched.
4. **§3.7 exchange 200.** (a) Subject: status code and persistence of a dispute exchange. (b) Enumerated: `routes_dispute.py record_exchange` (all three `exchange_type` branches return `ok(out_dispute(dispute))`), `store.py TABLES` (no exchanges table), `routes_dispute.py:106 file_dispute` (the one dispute endpoint that *is* 201), `routes_dispute.py resolve` (200 even though it creates a superseding draft). (c) Adjustment: dropped an initially drafted clause about restated `disputed_amount_cents` overwriting the dispute's figure — accurate, but outside the Step 7 item's scope.
5. **§3.7 `settled_on`.** (a) Subject: persistence/exposure of `settled_on`. (b) Enumerated: repo-wide grep for `settled_on` (only `routes_jib.py:202-203,209`), `store.py STATEMENT_FIELDS`, `jib_engine.py create_draft_statement`, `calc.py recompute_statement_totals`, and the obligation run's deemed-settlement path `routes_system.py evaluate_statements` (sets `SETTLED` without any `settled_on`). (c) Adjustment: kept the sentence to non-persistence/non-exposure only; did not name the error code the impl raises for a future-dated `settled_on` (`ERR_EFFECTIVE_DATE_OUT_OF_RANGE`) since that silence is not a Step 7 item.

Items deliberately NOT patched (traced, but PRD already determines them or they were pure fixture bugs): the `CLOCK_DEFAULT`/July->August remap and all derived date literals (§2.4 already fixes the epoch at `2026-08-01T00:00:00Z` and monotonicity); `bond_check_required_cents` and `total_billed_cents` (already the PRD's own field names in §3.3/§3.5/§3.6); the $250 overhead floor on an empty-pool draft (§3.5 already states the clamp applies unconditionally under both modes).

## Step 9: Complete PRD — 2026-09-03T21:43:15.744Z

ORCHESTRATOR DECISION (recorded rather than escalated, per autonomy): Step 9 was run as THREE
SEQUENTIAL file-partitioned passes over the same output file rather than one subagent, because a
single-pass scan of a 3,934-line / 20-module implementation reliably degenerates into a byte-identical
no-op copy of the source PRD. Partition: pass 1 = app/common/errors/store/validate/calc/jib_engine;
pass 2 = routes_lease/well/owner/afe/cost; pass 3 = routes_jib/dispute/revenue/transfer/system. Pass 1
created `PRD_COMPLETED.md` from `PRD_FINALIZED.md`; passes 2 and 3 edited it in place with the Edit tool
and were told explicitly not to re-copy or rewrite it, so no pass could clobber its predecessors.

Orchestrator verification: PRD_COMPLETED.md is 578 lines / 153,775 chars vs PRD_FINALIZED.md's
576 / 129,971 — +23,804 chars across 132 changed lines (66 line-pairs); NOT byte-identical, so the scan
really ran. All five top-level sections present, §5 still carries exactly 83 `ERR_` rows, and the file
ends on a complete final table row (no truncation). Also confirmed no code moved during Steps 8-9: the
newest `implementation/`, `test_suite/` and `test_helpers/` file mtimes are 20:56, before Step 8 began at
21:09 — so Step 7's independently-verified 8x81/81 green sweep still describes the shipped artifacts.

Aggregate across the three passes: 86 edits — 76 ambiguity-pins, 10 mismatch-revisions.

### Pass 1 (core modules) — 17 ambiguity-pins, 3 mismatch-revisions

Created `PRD_COMPLETED.md` as a byte copy of `PRD_FINALIZED.md` (576 lines), then edited only
PRD_COMPLETED.md. Result: 578 lines / 136,813 chars (+6,842).

- §2.1 — revise — ambiguity — `X-User-ID`/`X-User-Role` present-but-empty also 401, role match exact/case-sensitive — validate.py:24-28
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from A-Z0-9 — common.py:164-168
- §2.2 — revise — ambiguity — `api_request_timestamp` read from the host wall clock, not the logical clock — common.py:171-175
- §2.2 — insert — ambiguity — default `message` derived mechanically from `error_id`; message text not load-bearing — common.py:156-159
- §2.3 — insert — ambiguity — equal `created_at` tie-broken by write order; descending lease listing reverses that too — store.py:61-66
- §2.3 — insert — ambiguity — filters exact case-sensitive equality, conjunctive, non-matching value yields empty page, unknown query params ignored — validate.py:272-276
- §2.4 — insert — MISMATCH — `version` increments at most once per request per row even when written several times; each write still refreshes `updated_at` — common.py:218-233
- §2.4 — revise — ambiguity — `current_utc` parsing: trailing `Z` optional, offsets converted, offset-less read as UTC — common.py:73-87
- §2.5 rung 3 — insert — ambiguity — absent/unparseable body treated as `{}`; non-object JSON body is `ERR_VALIDATION`; optional field sent as `null` == omitted — validate.py:52-70
- §2.5 rung 4 — insert — ambiguity — date fields exactly 10 chars; integer fields accept integral floats but never booleans; decimal strings accepted, decimal places measured after stripping trailing zeros — common.py:51-70, validate.py:104-161
- §2.5 rung 6 — insert — ambiguity — unknown `allocation_id`/`cost_entry_id` -> `ERR_WELL_NOT_FOUND`, unknown `election_id` -> `ERR_AFE_NOT_FOUND` — calc.py:99-108
- §2.6 — insert — ambiguity — percentages/acreage/multiple serialize as bare JSON numbers (trailing zeros lost), cents as JSON integers, absent as `null` — common.py:178-189
- §2.9 — insert — MISMATCH — a recomputation whose result equals the stored value writes nothing: no `updated_at`, no `version` bump (this is what makes the obligation run idempotent) — calc.py:226-229,260-262,302-316
- §3.1 — insert — ambiguity — expiry also rewrites `committed_acres_total` (-> 0 after hop 1) in the same write — calc.py:513-516
- §3.3 — insert — ambiguity — the prospective `transfer_wi_pct` position is a separate, separately-rounded term even when the grantee already holds a position — calc.py:285-299
- §3.6 — insert — ambiguity — one line item per ACTIVE position; written in WI-desc order; a well with no active position issues with zero line items and no residual — jib_engine.py:57,150-167
- §3.6 — insert — ambiguity — capital-bucket redirect lapses when no consenting owner exists; residual stays with the largest holder — jib_engine.py:140-143
- §3.7 — insert — ambiguity — reversal lands on the owner's currently ACTIVE position, skipped if none; tested on `penalty_accrued_cents`, so withheld-only accruals are not unwound — calc.py:434-443
- §4 — insert — ambiguity — trailing slash not significant on any path — app.py:12
- §5 — insert — MISMATCH — `ERR_VALIDATION` is the only id with a non-fixed status: 404 unrouted path, 405 bad method, 500 unexpected fault, same envelope — app.py:39-46

Pass 1 also confirmed `errors.py` matches §5 id-for-id and status-for-status, and `store.py`'s
serialized field lists match §3 (including line items carrying only `id`/`created_at`).

### Pass 2 (routes_lease/well/owner/afe/cost) — 21 ambiguity-pins, 3 mismatch-revisions

578 lines before -> 578 after (24 in-paragraph Edits; Pass 1's 20 edits verified intact).

Mismatches:
- §3.2 — revise — MISMATCH — PRD claimed `well_name` unique across all wells; impl checks only `api_number` (no `ERR_DUPLICATE_WELL_NAME` exists). Now: no name uniqueness test, plus `api_number` shape — routes_well.py:50-58
- §3.4 — revise — MISMATCH — PRD claimed `afe_number` unique across every AFE; impl never checks it. Now: 1-32 chars, no uniqueness test — routes_afe.py:38
- §2.3 — revise — MISMATCH — §2.3 promised exact case-sensitive comparison for every filter, but `non_consent_flag` is boolean-parsed (`true`/`1`/`yes`, case-insensitive, stripped; anything else selects unflagged rows rather than an empty page) — routes_owner.py:203-206

Ambiguity pins: shut-in payment guard order (both tenure and shut-in-well guards report
`ERR_LEASE_NOT_HELD`, ahead of the two-payment limit; computed amount owed neither persisted nor
returned; a first payment omitting `shut_in_start_date` keeps the existing date) — routes_lease.py:148-168;
continuous operation (tenure violation -> `ERR_LEASE_NOT_HELD`; future `event_date` ->
`ERR_EFFECTIVE_DATE_OUT_OF_RANGE` after both state guards; lapsed/null `continuous_dev_deadline`
self-loop -> `ERR_LEASE_NOT_HELD`) — routes_lease.py:169-178; `PRODUCTION_ESTABLISHED` has no tenure
precondition and no clock comparison — routes_lease.py:184-187; both deadlines recomputed on every
lease-carrying response with no `version` move — routes_lease.py:22-26; negative `committed_acres` ->
`ERR_VALIDATION` at rung 4, exactly zero -> `ERR_ALLOCATION_EXCEEDS_LEASE` — routes_well.py:107,120;
pooling `effective_date` required, validated, never stored — routes_well.py:167-168; the
`allocation_factor_total` re-verification failure also reports `ERR_POOLING_MINIMUM_NOT_MET` —
routes_well.py:181-183; status-change `effective_date` required and discarded — routes_well.py:195-197;
`PLUGGED` compares the freshly computed bond requirement only, never writes it back —
routes_well.py:245-250; `contact_email` any non-empty string — routes_owner.py:42; compliance update
requires no field, empty subset accepted and still bumps `version`/`updated_at` — routes_owner.py:85-98;
the tax-id release sweep keys on the value supplied being true, never runs on false/omitted —
routes_owner.py:100-107; termination `effective_to` checked only as a calendar date, `TERMINATED` ->
`ERR_TERMINAL_STATE` leaving `ERR_INTEREST_NOT_ACTIVE` for `SUPERSEDED` — routes_owner.py:225-229;
AFE creation has no `well_status`/`pooling_status` gate beyond the terminal guard and does not write the
well — routes_afe.py:47-48; `ERR_INTEREST_NOT_ACTIVE` bites only when the owner holds some position,
otherwise `ERR_NOT_AN_INTEREST_HOLDER` — routes_afe.py:132-142; election closure never parses the body —
routes_afe.py:160-165; the `FAILED` branch does not write the well — routes_afe.py:212-220; `paid_date`
unconstrained relative to `incurred_date` and the clock — routes_cost.py:30; cost settlement has no state
precondition, so a `PAID` entry can be settled again — routes_cost.py:73-84; the owner-scoped line-item
channel is not ownership-restricted for a `PartnerRepresentative` — routes_owner.py:111-117; an
unresolvable nested owner `id` reports `ERR_INTEREST_OWNER_NOT_FOUND` — routes_owner.py:116.

No new error identifiers were needed.

### Pass 3 (routes_jib/dispute/revenue/transfer/system) — 38 ambiguity-pins, 4 mismatch-revisions

578 lines before -> 578 after (37 Edit operations, several bundling adjacent pins). Pass 1 + Pass 2 edits
verified still present by word-diff against PRD_FINALIZED.md plus five sentinel spot-checks.

Mismatches:
- §2.5 rung 11 — insert — MISMATCH — the terminal-state guard is NOT run on the two owner-disbursement endpoints; a `PAID` row reports `ERR_DISBURSEMENT_NOT_PAYABLE` (409), not `ERR_TERMINAL_STATE` — routes_revenue.py:246,267
- §3.6 — revise — MISMATCH — `statement_number` is 1-32 chars and never tested for uniqueness (PRD had asserted per-well uniqueness) — routes_jib.py:39
- §3.7 — revise — MISMATCH — all three of JIA / Partner / Audit may record any exchange type; the side named per move is descriptive, not enforced — routes_dispute.py:134
- §3.9 — revise — MISMATCH — `ppr_eligible_count` snapshots distinct OWNERS, not ACTIVE positions (an owner with two qualifying positions counts once) — routes_transfer.py:20-29,94

Ambiguity pins: clock-set returns 200 with a `data` object of exactly one field `current_utc` —
routes_system.py:29; the obligation run parses no body, runs five fixed phases in `created_at` order,
skips expired leases in the obligation phase, and a statement freed in the dispute phase can settle in
the same run — routes_system.py:231-248; each run counter counts only its own path and deemed
settlements are reported by no counter — routes_system.py:204-217,240-245; issuance carries no body and
none is parsed — routes_jib.py:103-110; barred posture and activity-class mismatch both report
`ERR_WELL_INVALID_STATUS`, `PLUGGED` caught a rung earlier so `PROPOSED` is what this gate reports —
routes_jib.py:113-121; the issue-time overlap check considers only ISSUED/DISPUTED/SETTLED statements —
routes_jib.py:124-133; issuance returns 200 with the statement, never the line items — routes_jib.py:139;
dispute filing: negative `disputed_amount_cents` fails rung-4 `ERR_VALIDATION`, zero is well-formed and
caught by the bill comparison — routes_dispute.py:44,81; that comparison reads one line item (first in
`created_at` order = largest-WI row) and an owner with no line item fails the same check —
routes_dispute.py:76-83; the statement is written only when not already DISPUTED, and dispute listing is
not ownership-scoped — routes_dispute.py:103-121; `exchange_note` 1-500 chars, a restated
`disputed_amount_cents` stored as supplied with integer-cent checking only — routes_dispute.py:136-176;
escalation reports `ERR_DISPUTE_NOT_RESOLVABLE` (409) then `ERR_REBUTTAL_DEADLINE_PASSED` (422) in that
order, leaves `deemed_in_favor_of_partner` false, bumps `version` by 1 and returns 200 —
routes_dispute.py:169-178; resolution requires `outcome` and `adjustment_amount_cents` non-null even on
UPHELD where 0 is the only admissible amount — routes_dispute.py:186-188; the deemed-in-favor UPHELD
refusal reports `ERR_DISPUTE_NOT_RESOLVABLE` ahead of both amount rules — routes_dispute.py:198-206;
ADJUSTED de-billing unwinds no `non_consent_recoverable_balance_cents` and returns 200 with the dispute,
never the superseding draft — routes_dispute.py:220-241; revision refuses a DISPUTED statement with
`ERR_STATEMENT_NOT_VOIDABLE` (409) — routes_jib.py:155-159; the replacement records the revising
accountant as `prepared_by_user_id` and returns 201 — routes_jib.py:165-175; `void_reason` required,
unbounded, not stored, absent from the response — routes_jib.py:183-194; `settled_on` out-of-range (422)
is evaluated after both state preconditions — routes_jib.py:206-210; `volume_units` carried to six
decimals, rounded half up on the way in, no input decimal-place limit — routes_revenue.py:33; revenue
listing filters `well_id`/`distribution_status`/`production_month` — routes_revenue.py:68; release
carries no body — routes_revenue.py:84-89; release gate order `ERR_REVENUE_NOT_ACCRUED` ->
`ERR_WELL_NOT_POOLED` (status) -> `ERR_WELL_NOT_POOLED` (allocation total) ->
`ERR_NOT_AN_INTEREST_HOLDER`, with `well_status` gating nothing — routes_revenue.py:91-100; tier-4
withholding capped by the position's balance floored at zero, tracked per position, a negative balance
withholds nothing and normalizes to 0 — routes_revenue.py:154-164; a position's balance is written back
only when it differs, so an all-zero position's `version` never moves — routes_revenue.py:193-196;
release returns 200 with the revenue record, a partner supplying a foreign `owner_id` filter gets
`ERR_OWNER_MISMATCH` (403), the detail read is not ownership-scoped — routes_revenue.py:208-238;
`NON_CONSENT_RECOVERY` needs `withheld > 0`, so a zero-gross-share row is created ACCRUED despite a zero
net — routes_revenue.py:173; suspense release reads no body and requires SUSPENDED, else
`ERR_DISBURSEMENT_NOT_PAYABLE` (409) for ACCRUED and PAID alike — routes_revenue.py:241-247; the
assignor's `owner_type` is tested before the assignee's and nothing requires the two parties to differ —
routes_transfer.py:68-71; transfer listing filters — routes_transfer.py:110-114; the election is never
persisted as a resource, the duplicate test is keyed on the acting `X-User-ID`, returns 200 —
routes_transfer.py:139-160; EXERCISE does not recompute `bond_check_required_cents`, so the stale
assignee figure is what the closing tests — routes_transfer.py:151-158; `closing_date` validated as a
calendar date and nothing else — routes_transfer.py:169; the assignor's ACTIVE-position test runs AFTER
the bond test, reporting `ERR_NOT_AN_INTEREST_HOLDER` out of ladder order — routes_transfer.py:186-193;
the assignor's replacement row copies `non_consent_flag` and the whole recoverable balance —
routes_transfer.py:212-225; the grantee's supersede-and-add row copies `is_operator`,
`preferential_right`, `non_consent_flag` and carries its own balance plus any released by a fully
conveyed assignor — routes_transfer.py:233-248; `bond_check_required_cents` is left untouched at closing
and the call returns 200 with the closed transfer — routes_transfer.py:264-272.

Pass 3 confirmed the Pass-2 handover note generalizes: statement issuance, revenue release, suspense
release and the obligation run all skip `body()` entirely, and each now carries a bodyless-endpoint pin.

## PIPELINE COMPLETE — 2026-09-03T21:43:15.744Z

Step 9 wrote `workspace/PRD_COMPLETED.md`. Final state: 81/81 tests passing in all 8 sweep rounds,
`SCAFFOLD.yaml` + both design indices, `PRD.md` -> `PRD_FINALIZED.md` -> `PRD_COMPLETED.md`,
`test_helpers/` + `test_suite/` at the task root, `workspace/implementation/` with `start.sh` and the
eight `results.{1..8}.json` from the final green sweep.
