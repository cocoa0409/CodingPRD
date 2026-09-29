# Worklog — task_2301_pension_risk_transfer_annuity_buyout

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2301_pension_risk_transfer_annuity_buyout/` and `tasks/task_2301_pension_risk_transfer_annuity_buyout/workspace/` (pre-allocated task name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T16:46:00.000Z

All three scaffold artifacts are complete and the linter is clean.

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_2301_pension_risk_transfer_annuity_buyout/`
- `SCAFFOLD.yaml` (§1.0–§1.7, 3677 lines) — contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, single top-level key, 3304 lines)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, single top-level key, 4986 lines)

**SCAFFOLD.yaml contents**
- 13 entities (PensionPlan root; DeRiskingStrategy, ParticipantRecord, BenefitAudit, LumpSumWindow, ParticipantElection, BuyoutTranche, AnnuityQuote, Insurer, IndependentExpert, AssetTransfer, ParticipantComplaint, SettlementEntry) — hybrid topology (tree plus tranche↔quote↔insurer graph and two junction entities)
- 13 state machines, `state_machine_shape: parallel` — ParticipantRecord carries three independent dimensions (participant × mortality × address), plus six cyclic machines (strategy revision, filing deficiency, election revocation, audit reopen, complaint re-triage, selection reset), branching quote/transfer/audit-variance forks, and compound RESIDUAL bubble-up
- 13 calculations (dual-basis accounting vs settlement liability and projected cost, lump-sum PV with a non-monotonic fee tier, benefit recomputation with a service cap, safest-available composite score, insurer committed capacity over closed lock intervals, transfer credited value in-kind vs cash, funded status in bp, data-confidence score) — integer cents/bp only, `round_half_up`
- 60 endpoints, 35 validation rules (priority-ordered), 66 error codes, 8 roles (segregation-of-duties + three entity-backed peers), 3 OCC `concurrency_rules`, `consistency_model: immediate`, logical clock at 2026-08-01T00:00:00Z

**Design files**
- §1.8: **21** difficulty instances across 9 dimension groups (dual-basis divergence, selector-basis flips, rounding-order pinning, non-monotonic fee tiers, three-dimension independence, bounded revision cycles, three multi-level cascades, four precedence/priority conflicts, four inclusive/strict boundary instances, two conserved-quantity invariants, one compensating reversal)
- §1.9: **69** corner instances over all nine permitted sections — entities 12, state_machines 16, calculations 10, validations 6, endpoints 5, errors 10, rbac 4, cross_cutting 5, consistency_model 1. 13 of those are `excluded_because` stubs citing §1.8 instances; the 56 with recipes contribute the linted calls.

**Verification**
- `scaffold_lint.py`: `VERDICT: clean lint` — 60 endpoints, 13 entities, 21 §1.8 + 56 §1.9 instances, **1294 calls** all conforming to §1.5 (endpoint declared, role allowed, required inputs present, captures resolvable), and every §1.1 FK reverse-reachable
- Error coverage audit: **0 of 66** codes uncovered by the two design files; no duplicate instance names across files; every `excluded_because` citation resolves to a real §1.8 instance name
- Fixes made this session: added the missing `Insurer.insurer_status` field to §1.1 (it was referenced by §1.2/§1.4/§1.5/§1.6 but undeclared), and renamed three RBAC/negative instances so the linter's negative-trigger detection applies to their intentional 403/409 calls

## Step 3: Copy shared files — 2026-09-01T16:47:27.000Z

Copied `INSTRUCTION.md` to `tasks/task_2301_pension_risk_transfer_annuity_buyout/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T17:02:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2301_pension_risk_transfer_annuity_buyout/workspace/PRD.md`.

**Size:** 491 lines, ~13,900 words.

**Structure**
- §1 Introduction — 3 paragraphs (de-risking decision chain, dual-basis gap, data-cleansing/safest-available reality, scope).
- §2 Global Specifications — 10 domain-named subsections: 2.1 Actors, Authentication and Segregation of Duties; 2.2 API Response Structure (verbatim fixed block); 2.3 Pagination and List Ordering; 2.4 The Logical Clock, Day Arithmetic and Interval Conventions; 2.5 Integer Money, Basis Points and Rounding Discipline; 2.6 Common Resource Properties and Versioning; 2.7 Path Resolution and Referential Existence; 2.8 Cascade Propagation, Parallel State Dimensions and Compound Bubble-Up; 2.9 Stale-Version Rejection on Supersede-Style Writes; 2.10 Order of Evaluation Across Validation Families.
- §3 Business Logic — 9 subsections: 3.1 Plan Registration, Valuation and the Settlement Amendment; 3.2 Evaluating the De-Risking Levers; 3.3 Cleansing Participant Data; 3.4 Auditing the Benefit Calculation; 3.5 Scheduling a Lump-Sum Window and Fanning Out Notices; 3.6 Participant Elections and Revocation; 3.7 Closing the Window: Cap Allocation and Disbursement; 3.8 The Annuity Buyout; 3.9 Post-Transfer Complaints, the Residual Plan and Termination.
- §4 endpoint table — exactly 4 columns, 60 rows.
- §5 error table — exactly 2 columns, 66 rows.

**Coverage audit**

Contract 1 (Field-Name Coverage) — **PASS.** Two independent derivations of the required identifier set both diff clean: pass 1 against the pre-built 184-identifier set (161 entity fields ∪ 103 endpoint body/query/path keys) → 0 missing; pass 2 re-derived 179 identifiers straight from the YAML → 0 missing. All 61 state-machine state names and all 66 error ids appear in backticks. One repair was needed: `plan_status` was only implied ("starts in `ONGOING` status") and is now named verbatim.

Contract 2 (Rule Coverage) — **PASS.** All 35 validations are stated with their exact error ids, and §2.10 reproduces the scaffold's priority ladder in order — a positional check aligned all 35 items 1:1 with priorities 1,2,3,10,12,20,22,24,26,30,40,41,42,45,50–57,60–67,70–73,80 — with 0 `applies_to` endpoint omissions across all families. All 75 transitions across the 13 state machines are described (51 with explicit `FROM → TO` arrows, 24 in equivalent prose such as "every non-superseded audit transitions to `SUPERSEDED`"); one repair added the `BenefitAudit` initial `OPEN` status so the `OPEN → PASSED` / `OPEN → CORRECTION_REQUIRED` fork has a stated origin. All 13 calculations are written out with every constant translated to its numeric value in prose (no operator or constant name leaks): both liability bases, dual-basis strategy projection with round-before-sum, tranche liability + readiness, benefit recomputation with the 420-month cap and inclusive 500-cent tolerance, the non-monotonic lump-sum fee ladder keyed on pre-fee PV, the skip-and-continue cap waterfall, the two weighted selection bases with floor-division points and 4-level tie-break, closed-interval capacity aggregation, in-kind vs cash credited value, strict-`>` settlement recognition with pro-rata AOCI, the confidence-score deduction ladder, and dual funded-status. All 39 POST endpoints' side_effects hops are covered, including the 4-hop window/tranche settlement cascades, the 3-hop triage cascade, and the compensating abandonment and remediation-reversal paths. No fuzzy quantifiers present.

Contract 3 (§3 Path Purity) — **PASS.** 0 violations: no backticked token in §3 begins with `/`, is a bare HTTP method, or combines method+path, and there are 0 raw `/prt/…` mentions outside backticks in §3. Paths and methods appear only in §1/§2/§4.

Also verified: §2.2 is byte-identical to `section-2.2-response-structure.md`; the §4 table matches the scaffold's 60 endpoints exactly (0 missing, 0 extra); no §3 skeleton headings borrowed from `example-prd.md`. The two withheld design files were never opened, and no sibling task directory was inspected.

## Step 5: Generate unit tests — 2026-09-01T18:09:31.000Z

All work is complete. Final state of the deliverable:

## Files created

`/home/ubuntu/github/CodingPRD/tasks/task_2301_pension_risk_transfer_annuity_buyout/`

**`test_helpers/` (9 modules)** — `__init__.py` (registers the error→HTTP map on import), `api_client.py` (60 endpoints), `api_errors.py` (66 codes), `types.py`, `test_users.py` (8 roles + `make_insurer_rep_headers` / `make_participant_headers` / `make_expert_headers`), `constants.py` (PRD literals + pure recomputations, incl. `days_after`), `factories.py`, `fixtures.py` (identity-threaded builders), `assertions.py`.

**`test_suite/` (conftest + 15 test modules, 161 tests)**

| file | tests | file | tests |
|---|---|---|---|
| test_01_strategy_projection_and_revision | 8 | test_11_lifecycle_transitions | 23 |
| test_02_insurer_selection_and_scoring | 7 | test_12_calculation_breadth | 9 |
| test_03_lump_sum_fees_and_eligibility | 6 | test_13_request_validation | 12 |
| test_04_participant_dimensions_and_audit_tolerance | 5 | test_14_endpoint_contracts | 11 |
| test_05_cascades_and_settlement_ledger | 9 | test_15_error_contracts | 23 |
| test_06_tranche_gating_and_transfer_priority | 8 | test_16_role_permissions | 9 |
| test_07_temporal_windows_and_capacity | 10 | test_17_concurrency_and_cascade_visibility | 8 |
| test_10_entity_shapes_and_topology | 13 | | |

## Coverage (design-index-only)

- **Queue A (§1.8 Difficulty): 21 / 21 non-stub instances covered**, 77 tags total, 2–3 tests per instance. Per rule: dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 3, priority_pair_validation_conflict 2, boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2.
- **Queue B (§1.9 Corner): 56 / 56 non-stub instances covered** — entities 12, state_machines 12, calculations 5, validations 6, endpoints 5, errors 8, rbac 4, cross_cutting 3, consistency_model 1.
- **13 `excluded_because:` stubs correctly emitted nothing** (5 calculations, 4 state_machines, 2 errors, 2 cross_cutting).
- Every test carries exactly one verbatim trailing `Design:` line; no untagged, dual-tagged, or dangling tags. **No instance was skipped outright.**

## Assertions dropped where the PRD does not uniquely derive the design's claim

1. **`insurer_capacity_closed_lock_intervals_touch_but_expiry_frees`** — dropped the claim that a bare `GET /prt/insurers/{id}` shows `committed_capacity_cents` falling to 0 once a lock ages out. The PRD only recomputes that field at lock and at abandonment, so a stored-vs-as-of-clock read is ambiguous. The instance's real boundary is asserted: touching closed intervals reject with `ERR_INSURER_CAPACITY_EXCEEDED` on 2026-11-30, the identical call succeeds on 2026-12-01, and 23,800,000 of premium is locked against 20,000,000 of capacity.
2. **`quoting_gated_on_plan_amendment_scope_not_plan_state`** — the design's tranche `settlement_liability_cents == 39182625` adds a 350 bp expense load that the PRD puts only in the strategy projection; asserted the PRD value 37,875,000.
3. `ERR_IDENTITY_MISMATCH` is **403** (PRD §5 table), not the design's 409.
4. An election scenario's participant figures were internally inconsistent (20000/60000/240 recomputes to 18000 → `CORRECTION_REQUIRED`); used PRD-derived zero-variance earnings.
5. The `PLAN_TERMINATION` entry's `pbo_settled_cents` is self-contradictory across PRD §3.9; not asserted.
6. `data_confidence_score` corrections: an exhausted locator ladder scores **40**, not 65; and 85 is `CLEAN`, so the design's `ERR_PARTICIPANT_DATA_NOT_CLEAN` claim at 85 was dropped.
7. Address-search-on-a-settled-participant dropped (PRD names no error id); asset-transfer not-found asserted with `validate_error_is_one_of` because family 3 (ownership) precedes family 4 (path existence).

## Verification run

161 unique test names, no duplicates; **every quoted PRD sentence confirmed as a literal substring of `workspace/PRD.md`** with an ≥8-word contiguous floor; pyflakes clean across `test_suite/` and `test_helpers/`; all 15 modules import successfully; every `api.*`, `fixtures.*`, `factories.*`, `constants.*`, `assertions.*` attribute referenced exists; all 66 error→HTTP mappings match the PRD table exactly; zero `skip`/`xfail`/placeholders; zero occurrences of the word "scaffold". Nothing under `workspace/implementation/` was read or written, and no sibling task directory was touched. pytest was not run (no implementation is in scope).

## Step 6: Generate implementation — 2026-09-01T17:42:00.000Z

Implementation complete and validated.

**Files created** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2301_pension_risk_transfer_annuity_buyout/workspace/implementation/`):

- `start.sh` — foreground launcher (guarded `pip install`, then `exec python3 app.py`), binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=2.0`
- `app.py` — app factory, blueprint registration, `ApiError`/`HTTPException`/catch-all error handlers (404→`ERR_NOT_FOUND`, 405→`ERR_METHOD_NOT_ALLOWED`, malformed body→`ERR_INVALID_REQUEST` 422, else `ERR_INTERNAL`)
- `db.py` — in-memory store, 13 collections, logical clock pinned to `2026-08-01T00:00:00Z` at boot, entity/versioning helpers
- `errors.py` — all 69 PRD §5 error IDs with exact HTTP codes
- `response.py` — `meta`/`response_type`/`data` envelope, object/list/error builders, pagination meta
- `middleware.py` — `X-User-ID`/`X-User-Role` auth for the 8 roles, typed field extraction, range/pagination validation, entity lookup + filter resolution
- `services/calculations.py` — integer-cents math (`round_half_up`, `apply_bp`, liabilities, confidence score, benefit recomputation, lump-sum PV, strategy projection, composite score, transfer expense, settlement recognition, funded status)
- `services/domain.py` — derived-field recomputation, cascade helpers, insurer capacity, settlement ledger, residual transition
- `routes/plans.py` (14), `routes/participants.py` (8), `routes/windows.py` (9), `routes/buyout.py` (24), `routes/complaints.py` (5)

**Endpoint count: 60** — `app.url_map` enumerates exactly 60 GET/POST routes, matching the PRD §4 table one-for-one.

**Boot + smoke:** the server boots cleanly from a fresh `start.sh` process (no seeded data — `GET /prt/participants` returns `total_count: 0` on boot) and answers requests immediately; `POST /prt/plans` returns a correct 201 envelope with `created_at: "2026-08-01T00:00:00.000Z"` and `accounting_funded_status_bp: 9500`. A full end-to-end driver (plan registration → strategy approval → settlement amendment → participant load and data cleansing → lump-sum window schedule/open/elect/revoke/re-elect/close/settle → expert engagement and opinion → insurer registration → tranche draft/assign/quote/select/pricing-lock → rejected shortfall transfer, carrier-rejected IN_KIND transfer, accepted CASH transfer → tranche settlement → RESIDUAL → complaint file/triage/audit-reopen/resolve/re-triage reversal → termination filing, RETURN_DEFICIENT, refile, APPROVE → TERMINATED → auth/RBAC/404/pagination/range/OCC error surfaces) now reports **0 failures and 0 server tracebacks**.

Two fidelity notes found while validating: the SPONSOR_RESPONSIBLE triage correctly reopens the participant's benefit audit, so the complaint cannot be resolved until that audit is closed (`ERR_AUDIT_STATE_INVALID`, PRD §3.9), and `APPROVE` on `filing-review` correctly enforces the `accounting_funded_status_bp >= 10000` solvency gate (`ERR_PLAN_ASSETS_INSUFFICIENT`, 402). Both were scenario-sequencing issues in my scratch driver, not server defects.

## Step 7: Run tests and iterate — 2026-09-02T02:57:36.000Z

Orchestrator note: the first Step 7 agent ran ~7 hours under extreme host contention (load average 250–1300 from other pipelines sharing the machine) and committed zero edits to disk; it was stopped and replaced with a fresh fix agent under a fast-iteration mandate. The summary below is from the replacement agent, which owned the loop to completion. Orchestrator independently re-verified its claim by parsing all eight `results.{1..8}.json`: 8 rounds × 161 tests, `failed == 0` in every round, all 222 non-passes carry the runner's `lsof` setup-timeout signature, 161/161 distinct tests passed in at least 3 rounds (minimum pass count 3), and the union of assertion failures across all rounds is 0.

The loop is complete. Final gate is clean.

## Summary

**Iterations run:** 4 diagnostic probe rounds (full-suite parallel probe → 31-test re-probe at concurrency 4 → 5-test re-probe at concurrency 2 → 1-test re-probe at concurrency 1), then the mandated 8-round parallel gate.

**Tests deleted:** none. No test in the suite produced an assertion failure at any point, so no test ever reached STEP 1 adjudication — there was nothing to test for PRD silence or non-unique-derivability.

**Fixes applied to `test_helpers/`:** none required.

**Fixes applied to `workspace/implementation/`:** none required.

### What the reported failures actually were

The handoff's "~101–114 passing out of 161" was not a defect signature — it was host-load noise, and the code needed no edits.

Every single non-pass observed across all probing and all 8 gate rounds (222 occurrences) carries one identical error signature:

```
failed on setup with "subprocess.TimeoutExpired: Command 'pids=$(lsof -ti:<PORT> -sTCP:LISTEN 2>/dev/null); [ -n "$pids" ] && kill -9 $pids 2>/dev/null; true' timed out after 5 seconds"
```

Root cause is in the shared runner infra, not the task: `prd_bench_local_runner/pytest_plugin.py::_kill_port` shells out to `lsof` with a hardcoded, uncaught `timeout=5`. On this host (~4700 processes, load average 207–228) `lsof` scanning `/proc` routinely exceeds 5s, and `--isolation per-test-server` invokes it before every one of the 161 tests. That is runner code I must not modify, and per the brief these are infra failures that do not count.

The noise is provably load-dependent, not test-dependent: the same tests pass when re-run at lower concurrency, and no test failed in more than 6 of the 8 gate rounds.

### Final 8-round gate result

Run exactly as specified (`--isolation per-test-server --timeout 240 --test-timeout 90`, no `--api-url`), results in `/home/ubuntu/github/CodingPRD/tasks/task_2301_pension_risk_transfer_annuity_buyout/workspace/implementation/results.{1..8}.json`:

| round | total | passed | failed | errors | assertion failures |
|---|---|---|---|---|---|
| 1 | 161 | 133 | 0 | 28 | 0 |
| 2 | 161 | 136 | 0 | 25 | 0 |
| 3 | 161 | 134 | 0 | 27 | 0 |
| 4 | 161 | 135 | 0 | 26 | 0 |
| 5 | 161 | 126 | 0 | 35 | 0 |
| 6 | 161 | 136 | 0 | 25 | 0 |
| 7 | 161 | 132 | 0 | 29 | 0 |
| 8 | 161 | 134 | 0 | 27 | 0 |

- **`failed == 0` in all 8 rounds.** Every non-pass is an `error` at setup, all 222 of them the `lsof` timeout above.
- **UNION of assertion failures across all 8 rounds: 0.** No flaky assertions.
- **All 161 distinct tests passed in at least 3 of the 8 rounds; 0 tests never passed.** Combined with the isolated re-probes, all 161 are independently confirmed green.

`workspace/implementation/`, `test_suite/`, and `test_helpers/` are byte-for-byte unmodified — the implementation was already fully PRD-faithful. My scratch tooling (probe dirs, probe/summarize scripts, gate logs) has been deleted; the only files left behind in the task tree are the eight gate `results.*.json` the specified command writes.

Orchestrator follow-up: an additional fully serial single round (concurrency 1, `--timeout 240 --test-timeout 90`) scored 124/161 with `failed == 0` and all 37 non-passes again carrying the runner's `lsof` setup-timeout signature and 0 non-infra errors — independent confirmation that the residual non-passes are host-load infrastructure noise, not assertion failures.

## Step 8: Finalize PRD — SKIPPED — 2026-09-02T03:00:00.000Z

Skip condition met exactly as the skill specifies: Step 7 required 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits at the sites Step 7 exercised, so no `PRD_FINALIZED.md` was produced and no subagent was spawned. Step 9 therefore starts from `PRD.md`.

## Step 9: Complete PRD — 2026-09-02T03:26:03.000Z

Done. `workspace/PRD_COMPLETED.md` is complete.

## Exit summary

**Files:** `workspace/PRD.md` 490 lines / 107,727 chars → `workspace/PRD_COMPLETED.md` 490 lines / 122,791 chars (**char delta +15,064**; line count unchanged — every change is an in-paragraph insert or revision, no new paragraphs except none, no new sections). `git diff --no-index` reports 56 modified lines.

**Counts:** 62 changes total — **50 ambiguity-pins**, **12 mismatch-revisions**.

### Global sections
- §2.1 — insert — ambiguity — blank/whitespace-only auth headers count as absent; header values are trimmed; a role outside the eight is `ERR_UNAUTHENTICATED`, not 403 — middleware.py:35
- §2.2 — insert — ambiguity — `api_request_id` is `req_` plus twenty random lower-case alphanumerics; `api_request_timestamp` comes from the logical clock, not wall time — response.py:19, response.py:23
- §2.3 — insert — ambiguity — status/enum filters are unvalidated: an unrecognised value matches nothing and yields an empty page — routes/participants.py:110
- §2.4 — insert — ambiguity — clock endpoint is open to all eight roles, accepts backward moves, answers `200` with empty `data`; body timestamps accept `Z`/offset/bare date, normalise to UTC, else `ERR_INVALID_REQUEST` — routes/plans.py:450, db.py:64
- §2.7 — insert — ambiguity — unmatched route → `ERR_NOT_FOUND` 404, unsupported method → `ERR_METHOD_NOT_ALLOWED` 405, trailing slashes tolerated — app.py:18, app.py:30
- §2.8 — revise — mismatch — the `PensionPlan` is exempt from the cascade version rule: its figures are rewritten in place without bumping `version`/`updated_at`; the plan bumps only on requests naming it and on the residual transition — services/domain.py:257, services/domain.py:286
- §2.10 item 3 — revise — mismatch — ownership-vs-existence split: complaints filing and expert opinion compare the raw path segment first; the other four resolve the entity first — routes/complaints.py:49, routes/buyout.py:400
- §2.10 items 6 & 7 — revise — mismatch — absent/unparseable body treated as `{}`; blank strings and length bounds live in family 6; lump-sum windows added to the family-7 list; asset-transfer amount bounds carved out as `ERR_INVALID_REQUEST` — middleware.py:52, routes/buyout.py:673
- §2.10 item 20 — revise — mismatch — `ERR_QUOTE_TRANCHE_MISMATCH` arises only on complaint filing; selection accepts no quote reference — routes/buyout.py:533
- §2.9 — (no change; already pinned)

### §3.1 Plan registration / valuation / amendment
- §3.1 — insert — ambiguity — duplicate `plan_ein` → `ERR_INVALID_REQUEST`, tested after shape and ranges — routes/plans.py:97
- §3.1 — insert — ambiguity — valuation update re-derives both `participant_liability_total_cents` and `accounting_funded_status_bp`; no `plan_status` precondition — routes/plans.py:144
- §3.1 — insert — ambiguity — ADOPT ordering (interval before own-state), `ERR_PLAN_STATE_INVALID`, `amendment_effective_date` echoed as full ISO instant — routes/plans.py:161
- §3.1 — insert — ambiguity — RESCIND ignores scope/date and requires `SETTLEMENT_AUTHORIZED` — routes/plans.py:190
- §3.1 — insert — ambiguity — rescission cascade stamps `abandoned_at`, leaves `abandonment_reason` null and the tranche's count/liabilities/readiness untouched — routes/plans.py:205

### §3.2 De-risking strategies
- §3.2 — revise — mismatch — `ldi_hedge_ratio_bp` is taken from the payload (default 0) and stored with no range check — routes/plans.py:310
- §3.2 — insert — ambiguity — submission tests the strategy's own `DRAFT` status before the plan's status — routes/plans.py:350
- §3.2 — revise — mismatch — the 350bp settlement expense load is applied **per participant** and summed, not to the base total — services/calculations.py:194
- §3.2 — insert — ambiguity — `RETURN_FOR_REVISION` records `decided_by_user_id`/`decision_rationale`; the `revision_count` bound precedes the SoD comparison — routes/plans.py:377

### §3.3 Data cleansing
- §3.3 — insert — ambiguity — duplicate `participant_reference` per plan → `ERR_INVALID_REQUEST`; `date_of_birth` required; `ssn_last4` optional four digits; `audited_monthly_benefit_cents` initialised to the stated figure — routes/participants.py:51
- §3.3 — insert — ambiguity — neither `NO_MATCH` branch re-evaluates a tranche's readiness — routes/participants.py:159
- §3.3 — insert — ambiguity — the tier-exhaustion test precedes the terminal-state test — routes/participants.py:159
- §3.3 — insert — ambiguity — a mortality outcome from an unaccepted source state → `ERR_PARTICIPANT_STATE_INVALID`, after shape checks — routes/participants.py:200
- §3.3 — insert — ambiguity — `DISPUTE_RESOLVED_DECEASED` leaves liabilities, elections and tranche untouched — routes/participants.py:249
- §3.3 — insert — ambiguity — `date_of_death` echoed as a full ISO instant with three fractional digits — db.py:56

### §3.4 Benefit audits
- §3.4 — insert — ambiguity — revised-figure ranges (earnings ≥ 0, service 0–600) and no state precondition on opening an audit — routes/participants.py:276
- §3.4 — insert — ambiguity — `resolution`, `override_rationale`, `reopened_by_complaint_id` null at creation; `OPEN` never observable — routes/participants.py:276
- §3.4 — revise — ambiguity — the five accepted resolution/status pairings; every other pairing `ERR_AUDIT_STATE_INVALID` — routes/participants.py:341
- §3.4 — insert — ambiguity — neither `PASSED_CLOSED` branch reaches a tranche — routes/participants.py:364
- §3.4 — insert — ambiguity — an already-`REOPENED` audit is simply re-stamped — routes/complaints.py:145

### §3.5–§3.6 Windows, notices, elections
- §3.5 — insert — ambiguity — window amounts raise `ERR_INVALID_AMOUNT` before `ERR_INVALID_INTERVAL` — routes/windows.py:54
- §3.5 — revise — mismatch — the quiet period is one-directional and unconditional: a proposal entirely *before* an existing window also conflicts — routes/windows.py:59
- §3.5 — insert — ambiguity — opening gates run notice-runway → own state/interval → plan authorization — routes/windows.py:105
- §3.6 — revise — ambiguity — election gates run in §2.10 order (audit-clean before mortality); wrong election state → `ERR_ELECTION_STATE_INVALID` — routes/windows.py:310
- §3.6 — insert — ambiguity — the `revocation_count` bound is a state-family test evaluated before the window-open and revocation-period gates — routes/windows.py:349

### §3.7 Cap allocation and disbursement
- §3.7 — insert — ambiguity — settlement re-pricing is read-only; each honoured election is paid its stored `net_lump_sum_cents` — routes/windows.py:219
- §3.7 — insert — ambiguity — the `LUMP_SUM_RECOGNITION` entry's `gain_loss_cents` repeats `amount_cents`; `source_reference` is `LumpSumWindow CLOSED -> SETTLED`; `tranche_id` null — routes/windows.py:246

### §3.8 Annuity buyout
- §3.8 — insert — ambiguity — duplicate `insurer_name` → `ERR_INVALID_REQUEST` after range checks; `state_guaranty_coverage_cents` optional, default 0 — routes/buyout.py:259
- §3.8 — insert — ambiguity — a rating action's optional `capital_ratio_bp` (0–20000 when supplied) and `insurer_status` leave stored values alone when omitted — routes/buyout.py:294
- §3.8 — revise — mismatch — the downgrade cascade only rewinds a tranche still `INSURER_SELECTED` whose `selected_quote_id` is that quote; readiness is *forced* to `BLOCKED` and count/liabilities are untouched — routes/buyout.py:318
- §3.8 — insert — ambiguity — participant assignment returns the tranche; gates run tranche state → plan/cohort coherence → single-tranche membership — routes/buyout.py:139
- §3.8 — revise — mismatch — stored tranche count/liabilities/readiness are not refreshed by the buyout settlement; they keep pre-settlement values — routes/buyout.py:786
- §3.8 — insert — ambiguity — quoting checks `DRAFT` first and the expert gate last, after the empty-tranche test — routes/buyout.py:160
- §3.8 — insert — ambiguity — selection rejects a non-`QUOTING` tranche with `ERR_TRANCHE_STATE_INVALID` first — routes/buyout.py:540
- §3.8 — revise — mismatch — selection names no quote, so `ERR_QUOTE_TRANCHE_MISMATCH` is never raised there — routes/buyout.py:556
- §3.8 — insert — ambiguity — final scoring tie-break is insertion order — routes/buyout.py:587
- §3.8 — revise — mismatch — pricing lock checks the live rating floor **before** quote expiry; an unresolvable selected quote/carrier is `ERR_TRANCHE_NOT_SELECTED` — routes/buyout.py:625
- §3.8 — insert — ambiguity — the post-lock carrier recompute covers the new lock interval and includes the locking tranche, so stored capacity is an interval snapshot — routes/buyout.py:653
- §3.8 — insert — ambiguity — cash deliveries need no lot count, the unused mode's amount field stays null, and the tranche must be `PRICING_LOCKED`; the supersede of an in-flight delivery happens only after the shortfall gate — routes/buyout.py:672
- §3.8 — insert — ambiguity — a surviving delivery stores `shortfall_cents` 0 and is the response body — routes/buyout.py:703
- §3.8 — insert — ambiguity — insurer-review returns the delivery record on both branches — routes/buyout.py:762
- §3.8 — insert — ambiguity — the "settled delivery" is the most recently created `SETTLED` delivery, with 0 fallbacks — routes/buyout.py:779
- §3.8 — insert — ambiguity — the `BUYOUT_RECOGNITION` entry's `window_id` is null and its `source_reference` is `BuyoutTranche ASSETS_TRANSFERRED -> SETTLED` — routes/buyout.py:798
- §3.8 — insert — ambiguity — abandonment recomputes carrier capacity over the released lock interval — routes/buyout.py:234
- §3.8 — insert — ambiguity — abandonment recomputes count and liabilities, leaves `selection_basis`/`data_readiness_flag` alone, and recomputes the plan's `participant_liability_total_cents` in place — routes/buyout.py:230

### §3.9 Complaints, residual, termination
- §3.9 — insert — ambiguity — `complaint_reference` is `CMP-%04d` over the plan's complaint count plus one — routes/complaints.py:42
- §3.9 — revise — mismatch — a supplied `tranche_id` is compared to the participant's **current** `tranche_id` as an opaque string, with no existence check — routes/complaints.py:60
- §3.9 — insert — ambiguity — a participant with no live audit still becomes `REOPENED`; the tranche's count/liabilities are untouched — routes/complaints.py:145
- §3.9 — insert — ambiguity — re-triage performs no audit-reopen hops and leaves `remediation_amount_cents` as recorded — routes/complaints.py:160
- §3.9 — insert — ambiguity — the five literal `source_reference` strings the ledger carries — services/domain.py:257, routes/complaints.py:185
- §3.9 — insert — ambiguity — `filing_reference` is required on every filing including re-filings — routes/plans.py:237
- §3.9 — insert — ambiguity — termination approval recomputes `participant_liability_total_cents` and `accounting_funded_status_bp` after the cascade — routes/plans.py:298

### §4
- §4 preamble — insert — ambiguity — which entity each multi-entity transition returns (participant for address/mortality, audit for audit resolution, tranche for assignment, delivery for insurer-review) — routes/participants.py:174, routes/buyout.py:152, routes/buyout.py:762

Verified as unchanged-and-already-pinned: §2.5–§2.7, §2.9, the §4 role lists and filter set (checked against every `authenticate(...)` call and every `filter_arg`/`request.args` use), and the §5 error/HTTP map.

## Step 7 final gate re-run (orchestrator) — 2026-09-02T05:48:45.000Z

The eight `results.{1..8}.json` shipped in `workspace/implementation/` come from a final 8-round parallel gate the orchestrator re-ran once host load had fallen from ~220 to ~130 (`--isolation per-test-server --timeout 300 --test-timeout 120`, no `--api-url`). The earlier gate's files were regenerated because only 4 of the 8 survived on disk. No source file was modified between gates — `implementation/`, `test_suite/`, and `test_helpers/` are the same bytes Step 5 and Step 6 produced.

| round | total | passed | failed | errors |
|---|---|---|---|---|
| 1 | 161 | 161 | 0 | 0 |
| 2 | 161 | 158 | 0 | 3 |
| 3 | 161 | 161 | 0 | 0 |
| 4 | 161 | 160 | 0 | 1 |
| 5 | 161 | 160 | 0 | 1 |
| 6 | 161 | 159 | 0 | 2 |
| 7 | 161 | 160 | 0 | 1 |
| 8 | 161 | 160 | 0 | 1 |

- **Two rounds are fully clean at 161/161** (rounds 1 and 3).
- `failed == 0` in all 8 rounds; the union of assertion failures across all rounds is **0**.
- All 9 remaining non-passes are setup `errors` carrying the runner's own `lsof` timeout signature (`prd_bench_local_runner/pytest_plugin.py::_kill_port`, hardcoded uncaught `timeout=5`), which is shared runner infrastructure the task must not modify.
- Every one of the 161 distinct tests passed in at least **7 of the 8** rounds; no test failed to pass.

Progression across gates as external load fell (source unchanged throughout) confirms the residual non-passes are host contention, not defects: 222 infra non-passes at load ~220 → 55 at load ~200 → 18 at load ~140 → 9 at load ~130, with assertion failures held at 0 in every gate. Supplemental single serial rounds scored 124/161 (load ~220) and 159/161 (load ~150), again with `failed == 0` and no non-infra errors.
