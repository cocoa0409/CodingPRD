# Worklog — task_2758_warranty_claim_adjudication_dealer_audit

## Step 1: Create task directory — 2026-09-04T17:18:51.717Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2758_warranty_claim_adjudication_dealer_audit` and its `workspace/` subdirectory. Index 2758 was pre-assigned by the orchestrating prompt; no scan of `./tasks/` was performed (other pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-04T18:46:00.000Z

All three scaffold artifacts for task 2758 are complete and lint-clean.

**Output directory:** `/home/ubuntu/github/CodingPRD/tasks/task_2758_warranty_claim_adjudication_dealer_audit/`

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 3373 | 165 077 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2140 | 160 245 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 5385 | 376 680 |

**SCAFFOLD.yaml (§1.0–§1.7)** — 14 entities, 50 endpoints, 49 error codes, 9 calculations, 8 state machines (WarrantyClaim carries two independent dimensions: `status` and `payment_status`), 4 `concurrency_rules`, 7 roles. `complexity_profile`: primary `compliance_audit` / secondary `ledger_reconciliation`; layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, derived_field_reconciliation]`; topology `graph`, shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`, `difficulty_level: expert_plus`. Verified to contain **neither** `scaffold_difficulty_design` nor `scaffold_corner_design`.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)** — single top-level key, 9 rule_ids / 22 instances: dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 4, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)** — single top-level key, all nine claim-extraction-guide sections, 95 instances (67 with full `test_recipe`, 28 `excluded_because` stubs citing a §1.8 instance): entities 12, state_machines 15 (9+6), calculations 12 (6+6), validations 25 (15+10), endpoints 6, errors 6, rbac 7 (6+1), cross_cutting_complexity_layers 11 (6+5), consistency_model 1.

**Verification**
- `scaffold_lint.py` → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (50 endpoints, 14 entities, 22 §1.8 instances, 67 §1.9 instances, 1116 calls scanned).
- Independent checks: instance `name` unique across the union of both design files (no dups, no overlap); every stub's cited `difficulty_instance` resolves to a real §1.8 instance name; no stub carries a `test_recipe`; all 4 §1.2.1 concurrency rules have a real OCC instance; **all 49 declared error codes are covered** by at least one §1.8 or §1.9 instance.

**Disclosure:** the directive line "Generate task harder than expert level!" was deliberately **not** copied into `scenario:` (which holds only the verbatim domain description); it is encoded instead as `complexity_profile.difficulty_level: expert_plus`. The hard constraint was honoured — no sibling `task_*/` directory or artifact was listed, globbed, grepped or read; the only inputs were the scenario text, `skills/prd-bench-scaffold-generator/SKILL.md`, its `references/claim-extraction-guide.md`, `scaffold_lint.py`, and this task's own three files.

**Orchestrator verification:** `grep -rn "harder than expert"` over the task dir returned no matches — the difficulty directive did not leak into any scaffold artifact.

## Step 3: Copy shared files — 2026-09-04T18:47:18.349Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T19:05:00.000Z

PRD generation complete.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2758_warranty_claim_adjudication_dealer_audit/workspace/PRD.md`

- **Final line count: 477**
- **Last section heading: `## 5. Error Code Catalogue`**
- `tail -40` confirms the file ends at a real boundary — the final row of the error table, `` | `ERR_GOODWILL_LIMIT_EXCEEDED` | 422 | `` — with no truncated sentence. Written in 8 quoted-heredoc `cat >>` appends, so nothing hit the output cap.

## Sections emitted (28 headings)
§1 Introduction; §2 Global Specifications with 11 subsections (2.1 Role-Based Access Control, 2.2 API Response Structure, 2.3 Pagination, 2.4 Record Identity/Timestamps/Version Counters, 2.5 Monetary Units & Rounding, 2.6 Logical Clock & Statutory Windows, 2.7 Nested Path Resolution, 2.8 Chargeback Ledger & Dealer Posture, 2.9 Version Pinning on Dependent Writes, 2.10 Segregation of Duties, 2.11 Order of Rejection); §3 Business Logic with 9 subsections (3.1 reference data/enrollment, 3.2 labor rate & markup, 3.3 claim intake & coverage, 3.4 provisional pricing & edit engine, 3.5 goodwill authority, 3.6 adjudication/payment/voiding, 3.7 parts return & non-return cascade, 3.8 on-site audit, extrapolation & appeals, 3.9 expense analytics & outlier detection); §4 Endpoint Definitions; §5 Error Code Catalogue.

## Scaffold coverage
- **Endpoints: 50/50.** §4 table has exactly 4 columns and 50 data rows (verified: 52 lines including header+separator, uniform 5-pipe width).
- **Error codes: 49/49.** §5 table has exactly 2 columns and 49 data rows. All 49 identifiers also appear in §1–§4 prose, each tied to the condition that raises it.
- **Calculations: all 10 scaffold `calculations:` blocks** (the header's "9 calculations / 4 variants" counts `claim_reimbursement_amount` and `dealer_warranty_expense_per_vehicle` as one each despite their 2 variants apiece). Every named constant is expressed in prose words or literal figures: 25% / 10% step-ups, 150,000-cent high-value threshold, 20-char narrative floor, 30/180-day repeat-repair window, 50% not-available share, 0.10/0.05 extrapolation tiers, 365-day analytics window, 1.50 outlier threshold, 50,000/250,000-cent goodwill bases with the decay factor and 80% share cap, 90,000/200,000-cent posture thresholds.
- **State machines: 9/9 scaffold blocks** (the "8" count merges `WarrantyClaim.status` and `WarrantyClaim.payment_status`). All states, all transitions and all four OCC rules are covered; three arrow-form edges are stated as set membership instead (`SUBMITTED` or `UNDER_REVIEW` → `APPROVED`/`DENIED`; `PENDING`/`ESCALATED` → `APPROVED`/`DENIED`/`WITHDRAWN`), and I added an explicit six-edge enumeration of the dealer posture machine in §2.8 since `PROBATION → SUSPENDED` was only implied.
- **Validations: 28/28** priorities mapped onto the 27-step §2.11 ladder (priorities 85 and 87 share `ERR_GOODWILL_LIMIT_EXCEEDED` and collapse into one rung).

## Hard Contracts
- **Contract 1 — Field-Name Coverage: PASS.** Scripted check over every `entities[].fields[].name` and every endpoint `input` identifier: 0 missing. (Note for future runs: naive `` `([^`]+)` `` extraction reports ~243 false misses because the §2.2 fenced JSON block skews backtick parity — fenced blocks must be stripped first.)
- **Contract 2 — Rule Coverage: PASS.** 49/49 error IDs in prose, all state-machine edges with preconditions and side effects, all four `expected_*_version` rules with field + error + 412, all calculations with pinned rounding order, all endpoint side effects including the five-hop non-return cascade, the four-hop late-return reversal, the six-step extrapolation order and the three symmetric appeal branches.
- **Contract 3 — §3 Path Purity: PASS.** 297 distinct backticked tokens in §3; 0 begin with `/`, 0 are bare HTTP methods, 0 are method+path pairs, and 0 raw `/warranty/...` strings appear in §3 prose.

Additional checks: §2.2 is byte-identical to `section-2.2-response-structure.md`; no fuzzy hedges ("approximately", "roughly", "conservatively", "e.g."), no operator syntax or pseudocode; no difficulty-directive or test-targeting language leaked. `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml` and all sibling `task_*/` directories were never opened.

Three scaffold self-conflicts were resolved and written explicitly: (1) labor-rate supersede applies to `SUBMITTED` rows only, per the state machine, leaving `UNDER_REVIEW` untouched; (2) issue-findings appends one `AUDIT_CHARGEBACK_SAMPLE` row per charged-back finding plus at most one `AUDIT_CHARGEBACK_EXTRAPOLATION` row with null `claim_id`; (3) appeal decisions append one `APPEAL_REVERSAL_SAMPLE` and one `APPEAL_REVERSAL_EXTRAPOLATION` delta row, each omitted when its delta is zero. The unmapped `approved_parts_qty <= claimed_parts_qty` precondition is routed to `ERR_VALIDATION` via the priority-35 body-shape rung.

**Orchestrator truncation check:** `wc -l` = 477; `tail -12` ends on the complete final error-table row `| ERR_GOODWILL_LIMIT_EXCEEDED | 422 |`; last heading is `## 5. Error Code Catalogue`. Not truncated — no regeneration needed.

## Step 5: Generate unit tests — 2026-09-04T20:07:00.000Z

Test generation is complete. Everything lives at the task root `/home/ubuntu/github/CodingPRD/tasks/task_2758_warranty_claim_adjudication_dealer_audit/` — nothing was created under `workspace/`, and `workspace/implementation/` was never read or written.

## Files written

`test_helpers/` — 2189 lines total
| file | lines |
|---|---|
| `__init__.py` | 32 |
| `api_client.py` | 275 |
| `api_errors.py` | 112 |
| `assertions.py` | 368 |
| `constants.py` | 68 |
| `factories.py` | 268 |
| `fixtures.py` | 634 |
| `test_users.py` | 50 |
| `types.py` | 382 |

`test_suite/` — 10159 lines, 147 test functions
| file | lines | tests | queue |
|---|---|---|---|
| `conftest.py` | 49 | — | — |
| `test_01_claim_pricing_dual_variants.py` | 318 | 4 | A |
| `test_02_pinned_formula_ordering.py` | 448 | 6 | A |
| `test_03_cyclic_state_machines.py` | 396 | 4 | A |
| `test_04_deep_cascades.py` | 418 | 4 | A |
| `test_05_rejection_priority_conflicts.py` | 483 | 6 | A |
| `test_06_inclusive_boundaries.py` | 458 | 8 | A |
| `test_07_cross_entity_state_dependency.py` | 277 | 4 | A |
| `test_08_temporal_overlap.py` | 275 | 4 | A |
| `test_09_compensating_invariants.py` | 325 | 4 | A |
| `test_10_entity_field_contracts.py` | 532 | 10 | B entities |
| `test_11_state_machine_transitions.py` | 668 | 9 | B state_machines |
| `test_12_calculation_formulas.py` | 755 | 8 | B calculations |
| `test_13_validation_rules.py` | 1269 | 30 | B validations |
| `test_14_endpoint_behaviours.py` | 941 | 12 | B endpoints |
| `test_15_error_catalogue.py` | 607 | 8 | B errors |
| `test_16_role_access_and_dealer_scope.py` | 869 | 11 | B rbac |
| `test_17_cross_cutting_layers.py` | 907 | 13 | B cross_cutting |
| `test_18_consistency_model.py` | 164 | 2 | B consistency_model |

## Coverage

- **Queue A (§1.8): 44 tests / all 22 difficulty instances, exactly 2 tests each.** No skips.
- **Queue B (§1.9): 103 tests / 65 of 67 non-stub corner instances.** All 28 `excluded_because:` stubs got no tests, and every stub's `difficulty_instance` pointer was verified to resolve to a real §1.8 instance.
- Verification: `py_compile` clean on all 28 modules; `/tmp/check_citations.py` → `tests: 147  instances tagged: 87  problems: 0`. 147 tagged tests == 147 `def test_` functions, so no test is untagged, dual-tagged, or pointing at a non-existent instance. Every PRD quote is verbatim and >=40 chars.

## Instances skipped (2, both `entities`, both on unique-derivability)

- `claim_computed_totals_ignore_client_supplied_extra_field` — asserts 201 for a body carrying `provisional_total_cents`/`coverage_type`; PRD §2.11 item 7 enumerates the body-shape checks and never licenses silently ignoring unrecognised keys, so accept-and-ignore vs `ERR_VALIDATION` are both faithful readings.
- `claim_system_fields_generated_client_input_ignored` — same premise for `id`/`created_at`/`version`/`status`, plus it pins `created_at` to the logical clock, which the PRD never ties together.

## Scaffold-vs-PRD conflicts resolved in the PRD's favour

- `statutory_ceiling_inclusive_boundary_17600_versus_17601` pins the petitioning dealer's version as unchanged; §3.2 says it advances by 1 — the version claim was dropped, not weakened into a wrong assertion.
- `vehicle_repair_overlap_closed_buffer...` places the 31-day claim *before* the anchor while also demanding a `REPEAT_REPAIR` edit; §3.4 makes that edit strictly directional, so the anchor was moved earlier (2026-03-11) and the probes run at +30/+31 days, preserving both the closed-buffer fork and a legitimate warn edit.
- Both labor-rate `state_machines` instances pin `Dealer.version == 2`; §3.2 makes filing itself a version bump, so those tests assert 3 (relative +1).
- `endpoints/2`, `errors/5`, `errors/6` and two receipt-date recipes were adjusted by their owning agents for the same reason (details in the per-file docstrings).

No server was started and no pytest run was attempted — verification was static (compile + citation/coverage audit), as planned.

**Orchestrator verification:** `find workspace -type d -name test_helpers -o -name test_suite` returned nothing — both dirs are correctly at the task root. `grep -rh "def test_" test_suite/*.py | wc -l` = 147; `grep -rh "Design: "` = 147 (1:1, no untagged tests).

## Step 6: Generate implementation — 2026-09-04T19:38:00.000Z

Everything is complete and the host is clean.

## Files written — `/home/ubuntu/github/CodingPRD/tasks/task_2758_warranty_claim_adjudication_dealer_audit/workspace/implementation/`

| File | Lines |
|---|---|
| `app.py` | 60 |
| `db.py` | 140 |
| `errors.py` | 73 |
| `middleware.py` | 71 |
| `response.py` | 60 |
| `util.py` | 262 |
| `requirements.txt` | 1 |
| `start.sh` (executable) | 10 |
| `routes/__init__.py` | 0 |
| `routes/common.py` | 97 |
| `routes/reference.py` | 330 |
| `routes/rates.py` | 211 |
| `routes/claims.py` | 482 |
| `routes/goodwill.py` | 160 |
| `routes/parts_returns.py` | 158 |
| `routes/audits.py` | 428 |
| `services/__init__.py` | 0 |
| `services/calc.py` | 300 |
| `services/cascade.py` | 161 |
| **total** | **3004** |

All files >200 lines were emitted in chunked `cat >>` appends; nothing was truncated. `__pycache__` dirs removed.

## Endpoints — 50 URL rules registered

- **Reference (`routes/reference.py`)**: state-law-profiles create/read/list, dealers create/read/list/patch, vehicles create/read/list, labor-operations create/read/list, parts create/read/list.
- **Rates (`routes/rates.py`)**: labor-rate-requests submit/read/list/decision (statutory ceiling by `RETAIL_SAMPLE` vs `TIME_AND_PRICE`), parts-markup-requests submit/read/list/decision, dealer expense analytics (`/warranty/dealers/<id>/expense-analytics`), chargeback ledger read/list.
- **Claims (`routes/claims.py`)**: submit, read, list, edits list, adjudicate, resubmit, pay, void.
- **Goodwill (`routes/goodwill.py`)**: create authorization, read, list, decision.
- **Parts returns (`routes/parts_returns.py`)**: read, list, receive, analysis, non-return-sweep.
- **Audits (`routes/audits.py`)**: schedule, read, list, start, attach finding, read/list findings, issue-findings, close, file appeal, read/list appeals, appeal decision.
- **Unprefixed**: `POST /_clock/set_current_utc`.

## Smoke test — passed

Two deep runs plus a final fresh-boot check. The final boot on port 10851 via `start.sh` returned a well-formed empty paginated array for `GET /warranty/dealers` (200), accepted the logical-clock set (`2026-08-05T00:00:00.000Z`), and rejected an unknown role with `ERR_UNAUTHENTICATED`. The earlier deep run ended `FAILURES: none` after exercising: pinned parts rounding (104157), the non-return sweep (debit 110000 -> PROBATION) and late-return reversal back to balance 0 / ACTIVE, the full audit lifecycle (error_rate 0.2727, factor 1.00, total 30000, appeal_deadline 2026-09-19, `ERR_APPEAL_PENDING` on premature close, SoD 403s, GRANT reinstating 30000 and clearing `audit_hold`), the goodwill path (margin 0.1, limits 40000/88000, coverage flip to GOODWILL releasing SUSPENDED->SUBMITTED), void + parts-return waiver, and the excessive-time suspend/resubmit cycle.

Both smoke servers were killed by exact PID (2470096 on 10847, 2585672 on 10851) located via `ss -ltnp`; both ports confirmed free. No pattern kill was ever issued, and no sibling task dir, corner/difficulty design file, `test_helpers/` or `test_suite/` was read or written.

Two interpretation calls worth flagging to the test author: `ERR_CLAIM_STILL_SUSPENDED` is raised on **APPROVE only** (the scaffold state machine and error catalogue disambiguate the unqualified PRD §3.6 prose), and `issue-findings` writes **one `AUDIT_CHARGEBACK_SAMPLE` ledger row per charged-back finding** (PRD over scaffold, which implied a single aggregate row). Filing an appeal stamps `appeal_id` on contested findings **without** bumping their version, per the PRD's conspicuous omission.

## Step 7: Run tests and iterate — 2026-09-04T20:37:00.000Z

All 8 parallel rounds pass 165/165. Exiting.

## Summary

**Iterations run:** 2 (each an 8-round concurrent sweep, `per-test-server` isolation).

- Iteration 1: 151/165 in all 8 rounds; the same 14 tests failed in every round (deterministic, no flakiness anywhere in the suite).
- Iteration 2: 165/165 in all 8 rounds.

**Tests deleted:** none. All 14 failures traced to verbatim PRD rules that a PRD-only reader derives uniquely, so nothing failed STEP 1.

**Fixes applied to `test_helpers/`:**

- `test_helpers/factories.py` — `create_labor_operation_payload()`: when a caller overrides `requires_causal_part` to `False` without also naming `causal_failure_group`, the factory now nulls the group instead of leaving its `"BRAKE_HYDRAULIC"` default in place. PRD §3.1 states "when it is false `causal_failure_group` must be null", so the old factory built a payload the PRD forbids and the PRD-faithful implementation correctly returned `ERR_VALIDATION` — 6 tests were failing as setup errors on this one fixture bug (the partless-operation dicts in test_04, test_06 and test_09 omit the key).
- `test_helpers/fixtures.py` — `submit_claim()`: the four reference ids are now merged into a dict that `**overrides` can override, rather than passed as positional-name kwargs alongside `**overrides`. Previously any caller overriding `vehicle_id` / `labor_operation_id` / `causal_part_id` raised `TypeError: got multiple values for keyword argument` before the request was ever issued.

**Fixes applied to `test_suite/`:**

- `test_suite/test_13_validation_rules.py` — `brake_claim_payload()`: same duplicate-keyword collision, same merge-dict fix. This was the direct cause of 7 `TypeError` failures (duplicate-repair-order, causal-part configuration, dealer scoping, and the two rejection-order tests). Assertions untouched.

**Fixes applied to `implementation/`:**

- `workspace/implementation/routes/audits.py` — issue-findings ledger append: `AUDIT_CHARGEBACK_SAMPLE` rows were writing `finding["id"]` into `source_id`; changed to `audit["id"]`. PRD §2.8: "The `source_id` points at ... a `DealerAudit` for the two audit chargeback codes". The extrapolation and appeal-reversal rows were already correct.

No implementation check was weakened, no assertion downgraded, no skip/xfail added, and storage remains in-memory with no seeded data. `worklog.md` untouched.

**Orchestrator verification:** all 8 `workspace/implementation/results.{1..8}.json` exist on disk (~56 KB each, all written 20:20) and were independently parsed by the orchestrator: every round reports `passed=165 total=165 failed=0`. The clean sweep is confirmed, not merely claimed.

Step 8 is NOT skipped: Step 7 applied 1 `implementation/` fix (plus 2 `test_helpers/` and 1 `test_suite/` fix), so the skip condition (0 fixes of every kind) does not hold.

## Step 8: Finalize PRD — 2026-09-04T20:29:00.000Z

`PRD_FINALIZED.md` is written. Exactly one edit was warranted; the other three Step 7 items were pure fixture/test-harness bugs or an implementation fix that moved the code *toward* verbatim PRD text.

## Line counts
- `PRD.md`: 477 lines / 101,981 bytes
- `PRD_FINALIZED.md`: 477 lines / 102,224 bytes
- Delta: 0 lines (0.0%); +243 bytes (+0.24%) — one sentence inserted mid-paragraph on line 188.

## Changes
- **§3.1 (Program Reference Data, labor-operation publication)** — *insert* — after the existing "when it is false `causal_failure_group` must be null", added that the pairing is enforced at publication rather than silently normalised, and that a violation in either direction (flag true with no non-empty group; flag false with a non-null group) is refused with `ERR_VALIDATION` — `implementation/routes/reference.py:243-248` (`util.bad` → `ERR_VALIDATION` per `implementation/util.py:15-16`).

## Per-edit pre-edit search log
**Edit 1 — §3.1 labor-operation `requires_causal_part` / `causal_failure_group` pairing**
- (a) Subject: publish-time consistency validation between `requires_causal_part` and `causal_failure_group` on `LaborOperation`, and which error code such a conditional body-shape violation carries.
- (b) Paths enumerated: `grep -rn "causal_failure_group|requires_causal_part"` across all of `implementation/` returned only two sites. Read `routes/reference.py:230-263` (the sole writer — `get_str(..., required=False)` treats an absent key and an explicit `null` alike, an empty string is rejected by `get_str`'s non-empty guard, a non-null group with the flag false is rejected explicitly, all four via `util.bad`); read `routes/claims.py:89-101` `check_causal_part` (the only reader — claim-side failures carry `ERR_CAUSAL_PART_REQUIRED`, a different code, so the wording had to stay scoped to publication); read `util.py:15-16,50-60,46-48` to confirm `bad()` is `ERR_VALIDATION` and null-vs-absent equivalence; checked the parallel conditional in `routes/reference.py:281-304` (`retention_days` must be 0 when `return_required` is false — also `ERR_VALIDATION`, PRD equally silent on its code) and confirmed no PATCH/immutability path revalidates labor operations anywhere. Also verified §2.11 item 7's body-shape → `ERR_VALIDATION` class is consistent with this.
- (c) Adjustment: wording deliberately scoped to "on publication" and phrased non-exclusively so it neither reaches the claim-submission `ERR_CAUSAL_PART_REQUIRED` path nor implies that the parallel `retention_days`/`return_required` rule (which Step 7 never exercised) is governed by any *different* code. Phrase "no non-empty group" chosen instead of "a null group" so the flag-true branch stays true of the empty-string case the impl also rejects.

## Items deliberately not patched
- `implementation/routes/audits.py` `AUDIT_CHARGEBACK_SAMPLE` `source_id` fix: PRD §2.8 already states verbatim that `source_id` "points at ... a `DealerAudit` for the two audit chargeback codes"; I verified `routes/audits.py:236-252` now passes `audit["id"]` for both audit codes and `:399-401` passes `appeal["id"]` for both appeal codes, matching §2.8. Impl was aligned to the PRD, so no PRD text change is needed.
- `test_helpers/fixtures.py` `submit_claim()` and `test_suite/test_13_validation_rules.py` `brake_claim_payload()`: both were Python duplicate-keyword `TypeError`s raised before any request was issued — no behavioral contract involved. I read the affected tests (duplicate repair order, causal-part configuration, dealer scoping, and the two rejection-order tests at test_13 test_29/test_30) and each asserts rules stated verbatim in PRD §2.7, §2.11, §3.3 and §3.6.

**Orchestrator verification:** `cmp` confirms `PRD_FINALIZED.md` differs from `PRD.md`; the diff is the single line-188 in-paragraph insertion described above and nothing else.

**Step 9 plan (orchestrator decision):** a single subagent cannot hold a 477-line / 102 KB PRD plus a 3004-line implementation and still do an exhaustive per-behavior scan, and a one-shot pass historically returns a byte-identical file (i.e. the scan never actually ran). Step 9 is therefore run as THREE SEQUENTIAL module-partitioned passes over one shared `PRD_COMPLETED.md`, each pass owning a disjoint slice of `implementation/`:
- Pass 1 (does the `cp PRD_FINALIZED.md PRD_COMPLETED.md`): global/infra + reference + rates — `app.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `util.py`, `routes/common.py`, `routes/reference.py`, `routes/rates.py`.
- Pass 2 (must NOT cp): claims + goodwill + `services/calc.py`.
- Pass 3 (must NOT cp): parts returns + audits + `services/cascade.py`.
Passes are strictly sequential so they never write the same file concurrently.

## Step 9: Complete PRD — 2026-09-04T21:31:00.000Z

Run as three sequential module-partitioned passes over one shared `PRD_COMPLETED.md`, per the plan recorded at the end of the Step 8 entry. 66 edits total (25 + 17 + 24), 55 of the 477 lines revised, zero lines added or removed, no new sections.

### Pass 1 of 3 — infra + reference + rates (`app.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `util.py`, `start.sh`, `routes/common.py`, `routes/reference.py`, `routes/rates.py`)

Performed the `cp PRD_FINALIZED.md PRD_COMPLETED.md`. 102,224 → 107,296 chars (+5,072). **21 ambiguity-pins, 4 mismatch-revisions.**

- §2.1 — revise — ambiguity — a header present but empty/whitespace-only is `ERR_UNAUTHENTICATED`, same as absent — `middleware.py:42`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars — `response.py:15`
- §2.2 — revise — ambiguity — `api_request_timestamp` comes from real server time, never the logical clock — `response.py:21`
- §2.3 — revise — ambiguity — a non-integer `limit`/`offset` is `ERR_VALIDATION`; an empty-string value is treated as omitted — `util.py:199`
- §2.3 — revise — ambiguity — equal `created_at` (the norm under a frozen clock) is tie-broken by server creation sequence — `db.py:107`
- §2.5 — revise — ambiguity — a supplied percentage with a third decimal is `ERR_VALIDATION`, not rounded — `routes/common.py:88`
- §2.5 — revise — ambiguity — a supplied hours value with a second decimal is `ERR_VALIDATION` — `routes/common.py:80`
- §2.6 — revise — ambiguity — clock endpoint returns `{current_utc}` normalised to 3 fractional digits; accepts no-`Z`, no-fraction, and bare date forms — `routes/reference.py:330`, `util.py:162`
- §2.7 — revise — ambiguity — an absent/null/non-string body FK is not an unresolvable reference; it falls to the shape pass — `routes/common.py:39`
- §2.10 — revise — **mismatch** — SOD reads the path record, so it runs after path resolution (ladder implied step 4 before step 5); a nonexistent id still yields 404 — `routes/rates.py:153`, cross-checked `routes/claims.py:376`, `routes/goodwill.py:106`, `routes/audits.py:354`
- §2.11 item 7 — revise — ambiguity — numerics/booleans accepted as JSON strings, integers as fraction-free numbers; string fields must be strings and non-empty even when optional; absent body = empty object, unparseable/non-object body = `ERR_VALIDATION` — `util.py:35,50,63,76,108`
- §3.1 — revise — ambiguity — every uniqueness constraint reports `ERR_VALIDATION`, tested after the rest of the body's shape checks — `routes/common.py:54`
- §3.1 — revise — ambiguity — `initial_labor_rate_cents` strictly positive; `initial_parts_markup_pct` 0.00–1.00 inclusive at two decimals — `routes/reference.py:84`
- §3.2 — revise — **mismatch** — the petition's `dealer_id` is taken at face value; filing is not dealer-scoped, so it is never compared to `X-User-ID` — `routes/rates.py:29` (no `scope_body` call)
- §3.2 — revise — ambiguity — an omitted sample field is recorded as null on the created request, in either statute method — `routes/rates.py:84`
- §3.2 — revise — ambiguity — the request opens with `approved_labor_rate_cents`, `approved_parts_markup_pct`, `denial_reason` null — `routes/rates.py:90`
- §3.2 — revise — ambiguity — an omitted `sample_repair_order_count` counts as zero for the sufficiency test — `routes/rates.py:55`
- §3.2 — revise — ambiguity — the review `note` is validated non-empty when present but never persisted — `routes/rates.py:130`
- §3.2 — revise — ambiguity — the decision's markup cap comes from the profile the *request* pinned, not the dealer's current one — `routes/rates.py:158`
- §3.2 — revise — ambiguity — the sweep reads `deemed_approved_days` from the request's pinned profile — `routes/rates.py:196`
- §3.2 — revise — ambiguity — multiple promotions of one dealer each write dealer terms in turn (last wins, one `version` bump each); `promoted_request_ids` is in ascending order — `routes/rates.py:204`
- §3.9 — revise — ambiguity — `window_start`/`window_end` are date-form query params, malformed = `ERR_VALIDATION`; defaults are the clock's calendar date; no ordering enforced — `routes/reference.py:151`
- §3.9 — revise — ambiguity — echoed window bounds are year-month-day; the report carries no `id`/`created_at`/`updated_at`/`version` — `routes/reference.py:166`
- §4 preamble — revise — **mismatch** — date-valued query params do error (`ERR_VALIDATION`) rather than matching nothing; empty filter = omitted; boolean filters accept `1`/`0`; trailing slashes tolerated — `util.py:224,237`, `app.py:25`
- §5 preamble — revise — **mismatch** — unknown path → `ERR_VALIDATION` at 404 and unsupported method → `ERR_VALIDATION` at 405, so `ERR_VALIDATION` is not bound to one status — `app.py:41-44`

### Pass 2 of 3 — claims + goodwill + calc (`routes/claims.py`, `routes/goodwill.py`, `services/calc.py`)

107,296 → 112,387 chars (+5,091). **11 ambiguity-pins, 6 mismatch-revisions.** Pass 1's 25 edits verified intact by diff.

- §2.9 — revise — mismatch — version field is compared only when supplied; mandatory only on a labor-rate request, optional on the other three creates where omission skips the check entirely (not `ERR_STALE_*`) — `routes/rates.py:41`, `routes/goodwill.py:42-44`, `routes/audits.py:66-67,291-292`. One softened sentence covers all four creates, so pass 3 skipped the audit/appeal version-requiredness subject.
- §2.7 — insert — ambiguity — `resubmission_of_claim_id` added to the claim-submission body-FK resolution order (last) — `routes/claims.py:138-142`
- §3.3 (narrative) — insert — ambiguity — absent/empty narrative → `ERR_NARRATIVE_INCOMPLETE`, non-string → `ERR_VALIDATION`; the fields are not treated as missing required strings — `routes/claims.py:33-51`
- §3.3 (causal part) — revise — mismatch — only three failures report `ERR_CAUSAL_PART_REQUIRED`; a named part with qty 0 is pre-empted as `ERR_VALIDATION` — `routes/claims.py:54-59,89-101`
- §3.3 (coverage) — revise — mismatch — the "no other transition of `coverage_type`" absolute is false: a correction redetermines coverage and sends `GOODWILL` back to `NONE` — `routes/claims.py:327`
- §3.3 (claim opening) — insert — ambiguity — approved-side fields and `oem_payable_cents` open null; `dealer_participation_cents`/`debited_amount_cents`/`reinstated_amount_cents` at 0; `void_reason`/`denial_reason` null — `routes/claims.py:190-201`
- §3.3 (claim list) — insert — ambiguity — `repair_date_from`/`repair_date_to` are inclusive bounds — `routes/claims.py:255-260`
- §3.3 (claim list) — revise — mismatch — "no create response exposes `resubmission_of_claim_id`" is false; every claim representation carries it — `routes/claims.py:175` + `response.py:26,30`
- §3.4 (`NARRATIVE_THIN`) — insert — ambiguity — the 20-char test is untrimmed, unlike the 10-char floor — `services/calc.py:135-136`
- §3.4 (return obligation) — insert — ambiguity — raising the obligation advances the dealer's `version` by 1 — `routes/claims.py:223-224`
- §3.4 (correction) — insert — ambiguity — both collision rules re-run on stored values with the claim itself excluded and the predecessor exempt; the causal-part rule can never fire on a correction — `routes/claims.py:300,310-318`
- §3.4 (correction) — insert — ambiguity — "every open edit" includes `DEALER_POSTURE_HOLD`, so a correction clears a posture hold — `routes/claims.py:325`
- §3.5 (limit refusal) — insert — ambiguity — an over-limit refusal precedes supersession, leaving the predecessor live and the claim's `version` unmoved; new authorizations open with `approved_amount_cents`/`decided_by_user_id`/`denial_reason` null — `routes/goodwill.py:55-59,67-81`
- §3.5 (escalated) — insert — ambiguity — `ERR_UNAUTHORIZED_FOR_ESCALATED_GOODWILL` sits after SoD, body shape and the state test and before the limit test (absent from the §2.11 ladder) — `routes/goodwill.py:123-143`
- §3.5 (approval cascade) — insert — ambiguity — the claim's own status is not a precondition; a DENIED/VOID claim still gets `coverage_type` `GOODWILL` and a `version` bump — `routes/goodwill.py:149-154`
- §3.5 (listing) — revise — mismatch — "only channel exposing which claim an authorization belongs to" is false; the create/read responses carry `claim_id` — `routes/goodwill.py:83,90`
- §3.6 (posture hold) — revise — mismatch — the `ERR_CLAIM_STILL_SUSPENDED` block applies to `APPROVE` only; a `DENY` goes through — `routes/claims.py:399-405`
- §3.6 (approval inputs) — insert — ambiguity — `approved_labor_hours` is one-decimal and may be zero (only negatives are `ERR_VALIDATION`) — `routes/claims.py:388-390`
- §3.6 (goodwill cap) — insert — ambiguity — the cap comes from the claim's *most recently created* `APPROVED` authorization — `routes/claims.py:335-339,360-363`

### Pass 3 of 3 — parts returns + audits + cascade (`routes/parts_returns.py`, `routes/audits.py`, `services/cascade.py`)

112,387 → 117,538 chars (+5,151). **11 ambiguity-pins, 13 mismatch-revisions.** All 42 prior-pass edits verified intact.

- §2.11 item 7 — revise — mismatch — `unsupported_amount_cents` "non-negative" → strictly positive, plus the <= `approved_total_cents` ceiling and `sample_size` strictly positive as shape rules — `audits.py:140-144,62-64`
- §2.11 closing paragraph — revise — mismatch — the false universal "only a posture recovery can lift" a `DEALER_POSTURE_HOLD`; now names correction/denial/voiding as the other resolvers — `cascade.py:33-38` (the sentence is at line 176 in §2.11, not §3.7 — §3.7 carries no such claim)
- §2.1 — revise — mismatch — dropped "or the `dealer_id` of the claim behind a parts-return request" from the scoping enumeration (impl scopes exactly the ten listed ops) — `parts_returns.py:42`, `middleware.py:51-54`
- §2.1 — insert — ambiguity — parts-return and audit-finding reads/lists are never scope-checked for a `DealerWarrantyAdmin` — `parts_returns.py:42,49`; `audits.py:175,182`
- §2.7 — revise — mismatch — `ERR_FINDING_NOT_FOUND` is path-parameter-only; contested/overturned array ids are not body FKs (→ `ERR_FINDING_NOT_IN_AUDIT` / `ERR_VALIDATION`) — `audits.py:300-305,363-371`
- §3.6 (void/denial waiver) — insert — mismatch — dealer row touched only when >=1 row was actually waived; zero waived leaves `version` unmoved — `cascade.py:139-151`
- §3.6 (payment dimension) — revise — mismatch — `CREDIT_REINSTATED` is not absolutely terminal: a later parts-return debit returns the claim to `DEBITED` — `cascade.py:122-125`
- §3.7 (analysis) — revise — ambiguity — `analysis_note` is required and non-empty — `parts_returns.py:104`
- §3.7 (analysis) — revise — mismatch — a non-`APPROVED` linked claim yields `debit_amount_cents` 0, not a refusal — `parts_returns.py:112`
- §3.7 (analysis debit) — revise — mismatch — `DEBITED` may also be entered from `CREDIT_REINSTATED` — `cascade.py:122-125`
- §3.7 (sweep hop 2) — insert — ambiguity — zero `approved_total_cents` still sweeps and marks the claim `DEBITED` but appends no ledger row and moves no balance/posture — `parts_returns.py:142-144`
- §3.7 (sweep hop 3) — insert — ambiguity — dealer `version` advances exactly once per run regardless of row count or zero debits — `parts_returns.py:145-151`
- §3.7 (late return) — revise — mismatch — the four compensating hops are conditional on a non-zero reversed amount, and the claim is credited only from `DEBITED` while the ledger row is appended regardless — `parts_returns.py:82-90`
- §3.7 (waiver recap) — revise — mismatch — dealer `version` moves only where a row was in fact waived — `cascade.py:148-150`
- §3.8 (start) — revise — mismatch — any `FieldAuditor` may start; `lead_auditor_user_id` is never compared — `audits.py:117-124`
- §3.8 (findings) — insert — ambiguity — the amount ceiling is a shape rule, so citing a never-approved claim reports `ERR_VALIDATION`, not the eligibility code — `audits.py:143-144` vs `155-159`
- §3.8 (findings) — insert — ambiguity — attaching a finding touches neither audit, claim nor dealer — `audits.py:160-170`
- §3.8 (issue) — revise — ambiguity — a cited `UNPAID` claim is charged back to the ledger but itself untouched — `audits.py:234-244`
- §3.8 (issue) — revise — ambiguity — dealer `version` advances by 1 even for an audit with no findings — `audits.py:253`
- §3.8 (appeal filing) — revise — mismatch — an id naming no finding at all is `ERR_FINDING_NOT_IN_AUDIT` — `audits.py:300-305`
- §3.8 (appeal filing) — revise — ambiguity — stamping `appeal_id` moves neither the finding's `version` nor `updated_at` — `audits.py:319-320`
- §3.8 (decision) — insert — ambiguity — `overturned_finding_ids` is read only for `PARTIAL` (ignored/unvalidated under GRANT/DENY) and duplicates collapse before the strict-subset test — `audits.py:363-371`
- §3.8 (decision) — revise — mismatch — only claims actually in `DEBITED` are credited back; a claim cited while `UNPAID` is skipped — `audits.py:407-408`
- §3.8 (granted close) — insert — ambiguity — a granted appeal closes the audit while leaving uncontested findings in `CHARGED_BACK` (only a manual close upholds them) — `audits.py:416-418` vs `270-273`

### Orchestrator verification

- `PRD.md` 477 lines / 101,981 chars → `PRD_FINALIZED.md` 477 lines / 102,224 chars → `PRD_COMPLETED.md` 477 lines / 117,538 chars (+15,557 chars, +15.3% over `PRD.md`).
- `cmp` confirms `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` — the scan genuinely ran (the historical failure mode of a byte-identical Step 9 output did not occur).
- `diff` reports 55 changed lines; no lines added or removed, so no section was dropped.
- `tail -4` ends on the complete final error-table row `| ERR_GOODWILL_LIMIT_EXCEEDED | 422 |`, last heading `## 5. Error Code Catalogue` at line 423. Not truncated.
- Step 9 edits touch documentation only; `implementation/`, `test_suite/` and `test_helpers/` are byte-unchanged since the Step 7 clean sweep, so the verified 8×165/165 result still stands.

## Pipeline complete — 2026-09-04T21:31:00.000Z

All nine steps finished. Final state: 14 entities / 50 endpoints / 49 error codes, 165 tests (147 test functions, 44 queue-A + 103 queue-B design-tagged), 3004-line Flask implementation, 8/8 sweep rounds at 165/165, and `workspace/PRD_COMPLETED.md` written.
