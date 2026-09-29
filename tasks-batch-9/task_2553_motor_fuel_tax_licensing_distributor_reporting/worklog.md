# Worklog — task_2553_motor_fuel_tax_licensing_distributor_reporting

## Step 1: Create task directory — 2026-09-03T09:29:16.791Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2553_motor_fuel_tax_licensing_distributor_reporting` and its `workspace/` subdirectory. Index 2553 was pre-assigned by the orchestrating prompt (no ./tasks/ scan, no auto-allocation) because up to 32 pipelines run concurrently on this host.

## Step 2: Generate scaffold — 2026-09-03T11:18:39.521Z

All three artifacts are complete, YAML-valid, and lint-clean.

## Output — `/home/ubuntu/github/CodingPRD/tasks/task_2553_motor_fuel_tax_licensing_distributor_reporting/`

| File | Lines | Contents |
|---|---|---|
| `SCAFFOLD.yaml` | 3240 | §1.0–§1.7 + preamble; no design keys present |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1673 | single key `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3832 | single key `scaffold_corner_design` |

**SCAFFOLD.yaml counts** — 14 entities, 8 state machines, 2 §1.2.1 concurrency rules (`bond-post-stale-licensee`, `amendment-create-stale-return`), 10 calculations, 79 ordered validations, 62 endpoints (`/mft` prefix), 75 errors, 6 roles. Profile: `ledger_reconciliation` / `compliance_audit`, layers [dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency, conditional_feature_flags], topology `graph`, shape `cyclic`, role_model `segregation_of_duties`, consistency `immediate`, level `expert_plus`.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 9 rule blocks / 20 instances, every one of the nine §0.5 rule_ids ≥2 (combinatorial_formula 3, boundary_precision_check 3, the rest 2).

**SCAFFOLD_CORNER_DESIGN.yaml** — all nine guide sections, 97 instances = 80 full recipes + 17 `excluded_because` stubs: entities 14, state_machines 16, calculations 13, validations 18, endpoints 11, errors 12, rbac 6, cross-cutting layers 6 (incl. one OCC recipe per §1.2.1 rule), consistency model 1.

**Verification** — `VERDICT: clean lint` (62 endpoints, 14 entities, 20 §1.8 + 80 §1.9 instances, 876 calls scanned); all 75 error ids triggered somewhere; 62/62 endpoints and every entity/machine/calculation/role referenced by at least one instance; 115 instance names unique across both files; no forbidden concurrency vocabulary in any file; every stub citation resolves to a real `rule_id / instance_name`.

## Design adjudications (scaffold self-contradictions found and fixed)
1. `ERR_ABATEMENT_AMOUNT_INVALID` (validation 505) was untriggerable — the abate endpoint accepts no amount. Rewrote the check (both the validations row and its error-catalog twin) to the client-reachable condition "balance already reduced by a payment, so a full reversal would mint a credit."
2. RefundClaim `REVIEWED -> PARTIALLY_APPROVED` cited `ERR_INVALID_REQUEST` where validation 410 declares `ERR_DECISION_AMOUNT_INVALID`; machine line corrected.
3. `AuditCase NONE -> ISSUED` cited the refund code `ERR_SEGREGATION_OF_DUTIES`; corrected to `ERR_ASSESSMENT_SEGREGATION_VIOLATION` (validation 107).
4. Validation 79's check omitted `TAXPAYER_RESPONSE` for assessments while the machine and error catalog allow it; widened to match.
5. `ExemptionCertificate.document_number` was described as unique per purchaser but validation 300 makes it globally unique; field description aligned to the validation.
6. `ScheduleLine.bill_of_lading_number` was described as unique per `schedule_id` but validation 402 keys it on `(return_id, counterparty_licensee_id)`; field description aligned.
7. A corner instance had misread validation 202 as an outbound-vs-inbound rule; it is a declared-vs-derived reconciliation, so the instance was rewritten (declared 1000.00 against lines 400.00 + 550.00 → 422, repaired by a 50.00 line → 30900 cents).
8. Two recipes used non-enum `transaction_type` values (`EXEMPT_SALE`, `DYED_SALE`) → `SALE`.
9. All duplicate-key asserts said HTTP 422; the catalog gives 409 (8 assert lines corrected).
10. Filing `days_late` uses **ceil** while assessment interest uses **floor**; the consistency-model instance was recomputed accordingly (clock 2026-09-24 → days_late 4, interest 31, penalty floor 5000, total 35931).
11. Validation 105's schedule-level limb (DYED_DIESEL on SCH_2/5/6) is unreachable through line creation because validation 200 rejects it at schedule creation; tested through the HIGHWAY-counterparty limb instead, with the schedule-level twin covered by the new `ERR_SCHEDULE_PRODUCT_NOT_ALLOWED` instance.
12. Rack branch 2e requires `purchaser.status == ACTIVE`, so a bonded-but-PENDING_BOND purchaser falls to branch 2f (TERMINAL_RACK); asserts corrected to `tax_amount_cents` / `DEFERRED_TO_PURCHASER` vocabulary.

## Step 3: Copy shared files — 2026-09-03T11:19:01.354Z

Copied `./INSTRUCTION.md` to `tasks/task_2553_motor_fuel_tax_licensing_distributor_reporting/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T11:36:00.000Z

The PRD is complete.

**Deliverable:** `workspace/PRD.md` — **546 lines**, written incrementally (one `Write` for the opening chunk, then `cat >>` heredoc appends), ending at a genuine boundary: the final row of the §5 error table. No audit footer, no contract block inside the file.

**Section list**
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Role-Based Access Control · 2.2 API Response Structure (verbatim fixed block) · 2.3 Pagination · 2.4 Common Resource Properties · 2.5 The Logical Clock · 2.6 Gallons, Rates and Rounding Discipline · 2.7 Bond Sufficiency as a Standing Precondition · 2.8 The Tax Ledger and the Money Invariant · 2.9 Cascade Discipline and Compensating Actions · 2.10 Stale-View Protection on Two Write Paths · 2.11 Path Resolution and Rule Precedence · 2.12 Segregation of Duties
- `## 3. Business Logic & Workflows` — 3.1 Licensing, Classification and the Consolidated Group · 3.2 Surety Bonds · 3.3 Terminals, Exemption Certificates and the Imposition Point · 3.4 Building a Monthly Return · 3.5 Filing, Interest, Penalty and the Amendment Chain · 3.6 Cross-Matching Supplier and Distributor Schedules · 3.7 Refund Claims · 3.8 Roadside Dyed-Fuel Enforcement · 3.9 Audit Selection, Casework, Assessment and Collection
- `## 4. Endpoint Definitions` — 62 rows, 4 columns
- `## 5. Error Code Catalogue` — 75 rows, 2 columns

**Coverage vs scaffold totals** (all machine-verified against `SCAFFOLD.yaml`): endpoints 62/62 (every method+path present in §4, roles copied programmatically from the scaffold, so `GET /mft/licensees` correctly excludes `LicenseeAgent`); errors 75/75 in §5 **and** 75/75 also referenced in §1–§3 prose; validations 79/79 expressed; calculations 10/10 expressed (`rack_removal_tax_imposition`, `monthly_return_tax_due`, `return_penalty_and_interest`, `licensee_bond_requirement`, `licensee_risk_score` both variants, `cross_match_variance`, `refund_allowable_gallons`, `dyed_fuel_penalty`, `assessment_amounts`, `licensee_balance`); state machines 8/8 with all 46 transitions; concurrency rules 2/2.

**Hard Contract 1 — Field-Name Coverage**: entities[].fields 138/138; endpoints[].request_body 73/73; endpoints[].query_params 39/39; computed-read output keys 13/13. Status: PASS

**Hard Contract 2 — Rule Coverage**: validations 79/79; OCC rejections 2/2; state transitions 46/46; calculations 10/10; validation→error_id matchable 79/79; side_effects 32/32; entity fields reconstructible 138/138; sibling-branch symmetry 7 groups, 0 asymmetric. Status: PASS

**Hard Contract 3 — §3 Path Purity**: 1139 backtick tokens scanned, 0 starting with `/`, 0 bare HTTP-method tokens, 0 method+path tokens. Status: PASS

Notes: the two withheld design files were never opened, and no sibling task directory was read. Where the scaffold contradicted itself the generator recorded a single consistent reading in prose (state machines preferred over narrower validation wording for abate/protest source states; the validations priority table preferred over entity-description parentheticals for `document_number` uniqueness ordering; `ERR_REFUND_BLOCKED_BY_AUDIT` treated as a filing-time check per priority 108). Two scaffold requirements with no dedicated error id — a `document_date` outside the parent return's `period_month`, and the `equipment_class`-required-iff-`PTO` rule — are expressed as `ERR_INVALID_REQUEST` conditional-shape failures.

**Orchestrator truncation check (per the known doc-generator failure mode):** independently verified — `wc -l` 546 / 110873 bytes; `tail -30` ends on a complete table row (`| ERR_PAYMENT_EXCEEDS_BALANCE | 422 |`) at a real section end; §4 contains exactly 62 method rows; §5 contains exactly 75 `ERR_` rows matching the scaffold's 75; 75 unique ERR_ ids appear in the document. Not truncated — no regeneration needed.

## Step 6: Generate implementation — 2026-09-03T12:20:00.000Z

(Steps 5 and 6 were launched as concurrent background subagents; Step 6 returned first, so its entry is recorded first. Note for the record: the two Agent calls went out in back-to-back messages rather than one message, so Step 6's impl generator was launched ~1 minute after Step 5's test generator instead of simultaneously. The physical isolation was therefore replaced by an explicit hard prohibition in Step 6's prompt against reading `test_suite/`, `test_helpers/`, and both design YAMLs; the subagent confirmed on exit that it read none of them.)

Implementation complete for task 2553.

## Files written (`workspace/implementation/`)

| File | Lines |
|---|---|
`start.sh` (executable, guarded pip, `exec python3 app.py`) | 10
`requirements.txt` | 1
`app.py` (envelope-safe JSON provider, 9 blueprints, error handlers) | 82
`db.py` (14 in-memory dicts, logical clock, `base_row`/`touch`, month helpers) | 205
`errors.py` (75 error ids → HTTP status + default message) | 168
`response.py` (meta/response_type/data, pagination) | 83
`middleware.py` (X-User-ID / X-User-Role, RBAC, licensee scope) | 70
`shape.py` (band-4 validators) | 192
`helpers.py` (`peek`/`ensure` ladder ordering, filters) | 162
`services/calc.py` | 261
`services/derive.py` (computed fields + 14 serializers) | 469
`services/cascade.py` (ledger, holds, cert rules, buffered overlap, case creation) | 152
`routes/licensees.py` | 288
`routes/terminals.py` | 130
`routes/removals.py` | 162
`routes/returns_bp.py` | 433
`routes/crossmatch.py` | 327
`routes/refunds.py` | 235
`routes/roadside.py` | 131
`routes/audits.py` | 233
`routes/clock.py` | 19

Total ≈3,813 lines. `python3 -m py_compile` clean on every `.py`.

## Endpoints: 62 of 62

Live Flask url_map diffed against the PRD §4 table (method + path, ids normalized): **IDENTICAL**, 62/62. Store starts empty on every boot; nothing seeded.

## Smoke tests (port 21553, killed by PID both times; no pattern kills)

End-to-end verified against PRD worked numbers: filing (tax 618000, days_late 36 by ceil, interest 5562, penalty 62356 at the 10% tier), assessment (penalty 50000, interest 4375 with floor-truncated days, total 554375), PTO 100 gal × 0.30 → 927 cents, reefer clamp 3000→1500 (46350) vs reject at 20000, bond min clamp 200000, risk 35/29 split, dyed penalty 100000 at 40 gal first offence. Cross-match: 2 cells, auto-escalation at 25000 gal creating a `CROSS_MATCH_ESCALATION` case, conservation law held after a write-off (25010 = 25000 + 10), `MATCH_VARIANCE`→`MATCH_RESOLVED`, `OPEN_AUDIT` holds applied on escalation and released on case closure. Error precedence spot-checked (segregation, stale version 412, `ERR_DISCREPANCY_STATE_INVALID` beating write-off legality, pagination 400, 401/403/404 family).

## PRD ambiguities resolved

1. **§3.6 vs §3.9 on escalated gallons** — §3.6 says an escalated variance "drops out" of the licensee-level `unreported_gallons_total`; §3.9 defines the input set as `UNREPORTED_BY_PURCHASER` and status **not in {WRITTEN_OFF, RESOLVED_EXPLAINED}** (so escalated rows stay). Followed §3.9's explicit set (scaffold `input_set` agrees); §3.6's sentence holds true for `open_discrepancy_count`.
2. **Refund gate order** — §3.7 names period-filed first in prose, but §2.11 bands put audit holds (10) before "refund period filed" (12). Implemented `ERR_LICENSEE_REVOKED` (9) → `ERR_REFUND_BLOCKED_BY_AUDIT` (10) → `ERR_REFUND_PERIOD_NOT_FILED` (12) → `ERR_EQUIPMENT_CLASS_INVALID` (13) → `ERR_REFUND_EXCEEDS_TAX_PAID` (14).
3. **`equipment_class` legality** — presence/absence conditional is band 4 (`ERR_INVALID_REQUEST`); an unrecognized class value and the reefer ×10 rejection are band 13 (`ERR_EQUIPMENT_CLASS_INVALID`), per §3.7's "either violation".
4. **Abate from `PROTESTED`** — scaffold validation #2072 says abate only from `ISSUED`; PRD §3.9 and the state machine legs say `ISSUED` or `PROTESTED`. Followed the PRD. Protest is `ISSUED`-only.
5. **No dedicated assessment-state error exists** — wrong `assessment_status` on protest/finalize/abate, and any action on a `CLOSED` case, return `ERR_AUDIT_CASE_STATE_INVALID` (409).
6. **Assessment issuance order** — `CLOSED` → `ERR_ASSESSMENT_ALREADY_ISSUED` → `ERR_AUDIT_CASE_STATE_INVALID` → `ERR_ASSESSMENT_SEGREGATION_VIOLATION` (PRD prose over scaffold priority numbers).
7. **POSITIVE inspection version** — the scaffold calls the in-request assessment a version-incrementing transition; the created row is returned with `version` 1 (creation, not a later mutation, per §2.4's "starts at 1 on creation").
8. **Revoked licensee + POSITIVE dye test** — recorded at `RECORDED` with `penalty_cents` 0, no ledger row (scaffold precondition `licensee.status != REVOKED`, no error declared).
9. **`ReturnSchedule` aggregate out ≤ in at filing** uses the declared `total_gallons` (identical to line sums, since the per-schedule reconciliation passes first) and applies only to `DISTRIBUTOR`/`BLENDER`/`RETAILER`.
10. **Cascade-created audit cases** get `risk_score_variant` `VARIANCE_WEIGHTED` (the entity default) and `selection_score` 0.
11. **LicenseeAgent narrowing** limited to the seven owner mappings §2.1 names, plus the protest endpoint (§3.9 "the audited licensee's own LicenseeAgent") — Terminal, ExemptionCertificate, RackRemoval, CrossMatchRun and RoadsideInspection reads are not narrowed.

Confirmed on exit: did not read `test_suite/`, `test_helpers/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, or any sibling task directory.

## Step 5: Generate unit tests — 2026-09-03T13:19:38.807Z

**Orchestrator note — generator death and resume.** The Step 5 subagent died mid-run at ~12:37 with `API Error: The system encountered an unexpected error during processing` after having written all of `test_helpers/` and `test_01`..`test_06` (67 tests). Rather than respawning a fresh generator (which would make the second half of the suite diverge in idiom from the first), the orchestrator computed the exact remaining work by diffing the emitted `Design:` tags against the non-stub instance sets in both design YAMLs — 20 Difficulty instances and 13 Corner instances outstanding — and SendMessage'd that to-do list to the SAME agent id, which resumed with its original context intact. Verified before resuming: all 67 existing tags unique and resolving to real non-stub Corner instances, all 15 existing .py files `py_compile`-clean.

Stage 2 is complete and fully verified.

## New files (this resume)

| File | Lines | Tests | Queue |
|---|---|---|---|
| `test_suite/test_07_difficulty_depth_calculations.py` | 714 | 8 | Difficulty |
| `test_suite/test_08_difficulty_depth_state_and_cascades.py` | 571 | 6 | Difficulty |
| `test_suite/test_09_difficulty_depth_conflicts_and_invariants.py` | 602 | 6 | Difficulty |

`test_10_rbac_and_layers.py` (951 lines, 10 tests) was finished earlier in the same resume. `test_helpers/` was reused unchanged (no restructuring, no broken imports); nothing was appended because every builder/assertion the new tests needed already existed.

## Suite totals

99 tests / 99 unique `Design:` tags, zero untagged, zero dual-tagged, zero duplicates, zero tags pointing at a non-existent instance.

- **Queue A (Difficulty):** 20 tests — all 20 §1.8 instances covered, one test each (`test_07` 8, `test_08` 6, `test_09` 6).
- **Queue B (Corner):** 79 tests across `test_01`..`test_06` + `test_10` — 79 of the 80 non-stub §1.9 instances. The 17 remaining yaml name-entries all carry `excluded_because` (stubs deferred to a named §1.8 instance) and were correctly not emitted; no stub instance was tagged.

`py_compile` on all 20 .py files in `test_suite/` + `test_helpers/`: ALL_COMPILED. pyflakes clean apart from the pre-existing re-export warnings in `test_helpers/__init__.py` and `conftest.py`.

The 4 "bad corner tags" flagged by an earlier ad-hoc script (`Corner/cross-cutting` x3, `Corner/consistency` x1) were confirmed to be script artifacts: that script split the tag on the *first* `/` and so truncated multi-word Corner section slugs at their embedded space. A corrected AST + indentation-tolerant yaml check reports `corner tags whose leaf is not a yaml name: []`. No genuine bug was found in `test_01`..`test_06`, so none were modified.

## Instances SKIPPED (gaps left as gaps)

- `Corner/entities/licensee_create_cannot_set_status_or_balance_system_fields` — **missing PRD coverage.** The PRD never declares what happens when a `POST /mft/licensees` body carries `status` or `balance_cents` (silently ignored vs. 422 vs. 400), so the asserted outcome is not derivable. No placeholder, no xfail.

## Limbs dropped from otherwise-emitted instances (weaker but PRD-derivable outcome asserted instead)

Each of these instances is still covered by a test; only the non-derivable sub-assertion was dropped:

- audit-case period ordering — yaml expects `ERR_DATE_RANGE_INVALID`; PRD does not uniquely derive that error id.
- second inquiry response — yaml expects `ERR_DISCREPANCY_STATE_INVALID`; not uniquely derivable.
- PTO `REEFER_TRAILER` 422 — refusal not declared.
- "`FREQUENCY_WEIGHTED` stored verbatim on a non-`RISK_SCORE` case" — PRD says the flag "is ignored", which contradicts the yaml's stored-verbatim limb.
- "all ledger rows stamped at `filed_at`" — PRD does not declare ledger row timestamps.
- TRANSPORTER `required_bond_cents == 750000` — the PRD's ceil-step formula yields 800000; the PRD figure was asserted.
- DRAFT return `tax_due_cents is null` — PRD only declares `attest_name`/`filed_at` null on a draft, so the test asserts those plus balance 0.

## Fixture substitutions (yaml data invalid against the PRD)

- The yaml's terminal control numbers `T41-MN-2553` and `T-MN-8400` violate the PRD's TCN pattern; `world.terminal()`'s generated control numbers were used.
- `MANUAL_REFERRAL` is not a member of the PRD's `selection_method` enum; `ROADSIDE_REFERRAL` was used.

**Orchestrator independent verification:** `test_suite/` totals 7207 lines across 11 files; 99 `Design:` tags, 99 unique, 0 unresolvable; the union of non-stub instances across both YAMLs is 100, so coverage is 99/100 with exactly the one documented skip; `py_compile` clean on all 20 files in `test_suite/` + `test_helpers/`.

## Step 7: Run tests and iterate — 2026-09-03T13:41:18.958Z

Clean 8-round sweep achieved. Summary below.

## Iterations run
**2.** Iteration 1 exposed 3 failures, identical in all 8 rounds (fully deterministic — no flakiness, no reaping; no `Terminated` in the sweep log). Iteration 2 was green.

**Final sweep: all 8 parallel rounds `99 passed / 0 failed / 99 total`.**

## Tests deleted
**None.** All three failures survived STEP 1 (PRD verbatim-covers the rule, and the rule uniquely determines the outcome) and were resolved at STEP 2 as test bugs.

## Fixes applied to `test_helpers/`
**None.** The faulty preconditions lived in the test bodies, not in shared fixtures/factories, so no fixture had wide reach here.

## Fixes applied to `test_suite/`
1. `test_04_validation_bands_and_priorities.py` — `test_a_rack_removal_is_refused_while_the_purchaser_carries_a_bond_deficiency`: setup built the purchaser with `world.new_licensee("DISTRIBUTOR")`, i.e. `PENDING_BOND`. PRD §3.3 puts the purchaser-status check among the *five business checks* that run *before* the single fiscal check, and says a `PENDING_BOND` purchaser "may not take delivery at a rack at all" → `ERR_PURCHASER_LICENSE_INVALID`. The fiscal rule under test is therefore unreachable from that state, so the implementation was correct. Switched the purchaser to `world.suspended_licensee("DISTRIBUTOR")` — the one state that both passes the status check ("must be `ACTIVE` or `SUSPENDED`") and carries a standing deficiency, exercising PRD's "whatever the purchaser's `status` happens to be". Bond-position assertions re-derived from PRD §2.7 accordingly (required `3000000` with the 2.0 suspension multiplier, posted `1500000`, deficiency `1500000`), and the curing bond raised to `3000000`. The test's original `TERMINAL_RACK` / `tax_imposed=True` / `227656` expectations were already consistent with a non-`ACTIVE` distributor purchaser (imposition branch 5 requires `ACTIVE`, so branch 6 applies) and were left untouched.
2. `test_05_endpoint_surfaces_and_actions.py` — `test_a_rack_removal_joins_three_references_and_404s_on_an_unused_one`: same class of bug, `world.new_licensee("RETAILER")` left the purchaser in `PENDING_BOND`. Changed to `world.active_licensee("RETAILER")`; the asserted `TERMINAL_RACK` outcome is exactly the PRD sentence the docstring already quoted ("a `BLENDER`, `TRANSPORTER` or `RETAILER` purchaser … is `TERMINAL_RACK`").
3. `test_08_difficulty_depth_state_and_cascades.py` — `test_a_second_positive_dye_test_reaches_all_the_way_to_a_refund_hold`: two mis-translations. The schedule code `SCH_2_REMOVED_TAX_UNPAID` is not one of PRD §3.4's six statutory codes (typo for `SCH_2_RECEIVED_TAX_UNPAID`), which failed the whole setup at HTTP 400. And `first["penalty_status"]` / `second["penalty_status"]` referenced a field the PRD never declares — PRD §3.8 says the inspection's **`status`** becomes `PENALTY_ASSESSED`. Both corrected toward PRD. Every downstream money assertion in the test (tax `500000`, penalties `150000`/`300000`, bond `3000000`/`1600000`/`1400000`, balance `950000`) verified against PRD arithmetic and left unchanged.

## Fixes applied to `implementation/`
**None.** No implementation defect was found. Notably, the rack-removal check ordering in `workspace/implementation/routes/removals.py::report_removal` (five business checks → duplicate-BOL → the single fiscal `ERR_PURCHASER_BOND_DEFICIENT` check, then the six-branch imposition ladder) already matches PRD §3.3 verbatim, and was the reason two of the three tests failed — the tests, not the server, were out of step.

**Orchestrator independent verification of the clean-sweep claim** (the known failure mode is a subagent claiming a green sweep with no artifacts behind it): all 8 `workspace/implementation/results.{1..8}.json` exist, all written 13:40, each parses to `passed 99 / failed 0 / total 99`. `sweep.log` contains 0 occurrences of `Terminated`, so no reaping incident. Suite integrity re-checked post-fix: still 99 unique `Design:` tags (0 deletions, matching the report), 0 `pytest.mark.skip` / `pytest.mark.xfail` markers anywhere in `test_suite/` or `test_helpers/`, and 0 hits for `sqlite` / `json.dump` / `/tmp/` in the implementation (in-memory storage only, nothing seeded).

**Step 8 gating decision:** Step 7 made 0 `implementation/` fixes and 0 deletions, but 3 `test_suite/` fixes, so the skip condition ("0 deletions, 0 test_suite fixes, 0 test_helpers fixes, 0 implementation fixes") is NOT met. Step 8 runs, with the three test_suite fixes as its `<step_7_diff>` focus list.

## Step 8: Finalize PRD — 2026-09-03T13:46:01.918Z

Done. `PRD_FINALIZED.md` is produced; after full verification of all three Step 7 items against `implementation/`, **no PRD edit was warranted** — every behavior the three test fixes turned on is already pinned verbatim in `PRD.md`.

## Line counts
- `PRD.md`: 546 lines
- `PRD_FINALIZED.md`: 546 lines — **0 changed lines, 0.0% delta** (byte-identical copy; `diff` clean)

## Changes
None. All three `<step_7_diff>` items are pure test-side bugs (mis-set preconditions and a field/enum typo), consistent with Step 7's own "0 implementation fixes, 0 deletions".

## Per-item analysis log (subject → impl paths enumerated → verdict)

**Item 1 — fiscal bond-deficiency check reachable for a non-ACTIVE purchaser (`test_04`)**
- (a) Subject: the rack-removal purchaser-status gate, the `would_defer` shape, the deficiency derivation, and imposition branches 5/6 for a `SUSPENDED` purchaser.
- (b) Paths enumerated: `implementation/routes/removals.py:45-46` (status gate), `:58-61` (duplicate-BOL), `:64-68` (`would_defer` + `ERR_PURCHASER_BOND_DEFICIENT`), `:87-99` (six-branch ladder), `:102-116` (money); `services/derive.py:92-105` (`bond_position`), `services/calc.py:166-174` (`required_bond_cents`, ceil-then-clamp), `:158-163` (`average_liability_cents`); every other `bond_position(` callsite — `services/cascade.py:57`, `routes/licensees.py:95/217/236`, `derive.py:205`; `services/cascade.py:64-87` (`cert_validly_presented` / `cert_active_on_date`); grep of `ERR_PURCHASER_LICENSE_INVALID` / `ERR_PURCHASER_BOND_DEFICIENT` across `implementation/` (each appears in exactly one route).
- (c) No wording change needed. PRD §3.3 ¶220 pins the status gate ("must be `ACTIVE` or `SUSPENDED`"), ¶222 pins the fiscal check's reachability verbatim ("**whatever the purchaser's `status` happens to be**") and its position ("last, after the duplicate-bill-of-lading check", reinforced by §2.11 bands 10→13→14), branch 6 pins "**or a suspended supplier or distributor** → `TERMINAL_RACK`", and §2.7 ¶109 pins the 2.0 suspension multiplier that creates the deficiency. Impl's `certificate is None` in `would_defer` is *equivalent* to PRD's "no valid exemption certificate has been presented", because the five preceding business checks already reject any presented certificate that is not ACTIVE-in-window, holder-matched, and product-covered — so no rewording is needed there either.

**Item 2 — `RETAILER` purchaser must be activated; outcome `TERMINAL_RACK` (`test_05`)**
- (a) Subject: purchaser-status gate for a `RETAILER` purchaser, imposition branch 6, and body-FK resolution order for rack removals.
- (b) Paths enumerated: `routes/removals.py:22-42` (declared field order → `terminal_id` resolves first), `:45-46`, `:87-99`; `services/calc.py:63-68` (`BOND_TYPE_MULTIPLIER["RETAILER"] = 0.25`); `test_helpers/fixtures.py:127-145` (`active_licensee`/`suspended_licensee` construction path) as auxiliary evidence only.
- (c) No wording change needed. PRD §3.3 ¶220 (PENDING_BOND purchaser refused with `ERR_PURCHASER_LICENSE_INVALID`), branch 6 ("a `BLENDER`, `TRANSPORTER` or `RETAILER` purchaser … is `TERMINAL_RACK`"), and §2.11 band 7 ("in the order the fields are declared on the request") each determine the asserted behavior exactly.

**Item 3 — schedule-code enum and inspection status field/value (`test_08`)**
- (a) Subject: the legal `schedule_code` enum member set (rejection status for a non-member), and the inspection field name/value written on penalty assessment.
- (b) Paths enumerated: `services/calc.py:47-54` (`SCHEDULE_CODES`, exactly PRD's six), `routes/returns_bp.py:196/202/272` (every other consumer of `SCH_2_RECEIVED_TAX_UNPAID`), `shape.req_enum` band-4 rejection → 400; `routes/roadside.py:63-67` (`status` initialised `RECORDED`), `:77` (`status = "PENALTY_ASSESSED"`), `:121-125` (dismissal reads/writes the same `status`), `services/derive.py:415-429` (`inspection_json` exposes `status`, `prior_positive_count`, `penalty_cents`, `dismissal_reason` — no `penalty_status` field anywhere), `derive.py:122-127` (`dyed_violation_count` keyed on `status == "PENALTY_ASSESSED"`), grep of `PENALTY_ASSESSED` across `implementation/` (roadside route + derive only).
- (c) No wording change needed. PRD §3.4 ¶245 enumerates exactly the six statutory schedule codes (so `SCH_2_REMOVED_TAX_UNPAID` is an illegal enum member → §2.11 band 4 `ERR_INVALID_REQUEST` 400), and §3.8 ¶349/¶355/¶347 pin the field as `status` with values `RECORDED` / `PENALTY_ASSESSED` / `DISMISSED`. The `penalty_status` name the test used was never PRD vocabulary and is absent from the implementation, so there is nothing to pin.

Deliberately **not** edited (out of `<step_7_diff>` scope, recorded for Step 9's benefit rather than acted on): PRD §3.3 ¶222's non-normative aside that "the deferral branch … can always assume a fully bonded purchaser" is slightly stronger than the implementation (a presented non-GOVERNMENT/AGRICULTURE certificate with `destination_state == MN` bypasses `would_defer` yet can still reach branch 5), and PRD §3.6 ¶317's claim that an *escalated* variance drops out of the licensee-level `unreported_gallons_total` while `derive.py:155-162` excludes only `WRITTEN_OFF` and `RESOLVED_EXPLAINED`. Neither traces to a Step 7 fix.

**Orchestrator note:** `PRD_FINALIZED.md` verified present and byte-identical to `PRD.md` (110873 bytes each, `diff` clean). For Step 8 this is a legitimate result — Step 7 reported 0 implementation fixes and 0 deletions, so there was no impl-pinned choice to document. Step 9 is therefore the step that carries all the real alignment work, and the two divergences Step 8 flagged above (§3.3 ¶222 deferral-branch aside; §3.6 ¶317 escalated-variance exclusion set) are handed to it as concrete leads. Because a byte-identical `PRD_COMPLETED.md` would be evidence the Step 9 scan never actually ran, Step 9 is being run as three sequential file-partitioned passes over `implementation/`, each pass editing the same `PRD_COMPLETED.md`.

## Step 9: Complete PRD — 2026-09-03T14:16:12.747Z

**Orchestrator decision:** because Step 8 legitimately produced a byte-identical `PRD_FINALIZED.md` (0 impl fixes, 0 deletions in Step 7), the entire alignment burden fell on Step 9, and a byte-identical `PRD_COMPLETED.md` would have been evidence the scan never ran. Step 9 was therefore executed as THREE SEQUENTIAL file-partitioned passes over `implementation/` (3802 lines), each pass editing the same `PRD_COMPLETED.md` in place with targeted Edit calls:
- Pass 1 — infra/global layer (`app.py`, `db.py`, `errors.py`, `response.py`, `middleware.py`, `shape.py`, `helpers.py`, `routes/clock.py`) + licensing/bond/terminal/certificate (`routes/licensees.py`, `routes/terminals.py`).
- Pass 2 — rack removals, returns/schedules/lines/filing/amendments, cross-matching (`routes/removals.py`, `routes/returns_bp.py`, `routes/crossmatch.py`).
- Pass 3 — refunds, roadside enforcement, audits/assessment/collection (`routes/refunds.py`, `routes/roadside.py`, `routes/audits.py`) + final whole-document consistency read.
Each pass received the prior passes' scope as context so it would widen rather than revert their wording. Passes 2 and 3 were also handed the two divergences Step 8 had flagged out-of-scope, and the eleven PRD ambiguities the Step 6 implementation generator had self-reported.

### Pass 1 — infra + licensing (13 ambiguity-pins, 3 mismatch-revisions)
- §2.1 (auth headers) — revise — ambiguity — headers whitespace-stripped before the empty/recognized tests, so whitespace-only `X-User-ID` is 401 and a padded role name is accepted — `middleware.py:38-41`
- §2.1 (agent scoping) — insert — ambiguity — sub-collections/computed reads under a licensee path are scope-checked on the path licensee (403) rather than silently narrowed; narrowing is only for top-level lists — `routes/licensees.py:199,235,263`, `helpers.py:134-140`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + 20 uppercase-alphanumeric characters — `response.py:19-20`
- §2.2 — revise — ambiguity — `api_request_timestamp` read from the logical clock, not host wall time — `response.py:26`
- §2.3 — insert — ambiguity — empty-string `limit`/`offset` count as omitted; a decimal or non-digit body is not an integer → `ERR_INVALID_PAGINATION` — `response.py:44-58`
- §2.3 — insert — ambiguity — `created_at` ties broken by creation order; undefined query params ignored, and a defined filter with an unrecognized value matches no rows instead of erroring — `db.py:154-164`, `helpers.py:72-86`
- §2.4 — insert — ambiguity — a row touched several times inside one request advances `version` by exactly one and carries a single `updated_at` — `db.py:128-151`
- §2.5 — revise — ambiguity — `current_utc` is the sole member of `data`, three fractional digits, HTTP 200 — `routes/clock.py:13-19`
- §2.6 — insert — ambiguity — gallons are JSON numbers, never strings, quantized to two decimals — `app.py:17-26`, `services/derive.py:13-17`
- §2.8 — revise — **mismatch** — a `PAYMENT` row carries `source_entity_type` `Payment` with a **null** `source_entity_id`, its `effective_date` is the one submitted with the remittance rather than the clock's, and `memo` is null when none is supplied — `services/cascade.py:10-23`, `routes/licensees.py:285-286`
- §2.11 (band 6) — insert — ambiguity — an unresolvable addressed id yields that resource's 404 even for an out-of-scope `LicenseeAgent` — `helpers.py:134-146`, `routes/licensees.py:64-67`
- §3.1 — insert — ambiguity — the duplicate-`fein` check precedes parent-group validation, so a request failing both reports `ERR_DUPLICATE_FEIN` — `routes/licensees.py:34-42`
- §3.1 — revise — **mismatch** — the revoked test precedes the legal-transition test, so activate/suspend on a `REVOKED` licensee reports `ERR_LICENSEE_REVOKED` while a second revoke reports `ERR_LICENSEE_STATE_INVALID` — `routes/licensees.py:88-91,112-115,131-132`
- §3.2 — insert — ambiguity — `amount_cents` below 100000 is a band-4 `ERR_INVALID_REQUEST`, not a fiscal refusal — `routes/licensees.py:161-162`
- §3.3 — insert — ambiguity — certificates have no owning licensee for scope purposes, so an agent may read/list every certificate — `routes/terminals.py:98-116`
- §3.3 — revise — **mismatch** — `reason` is required on certificate revoke but is **not** persisted/returned — `routes/terminals.py:122-130`, `services/derive.py:249-259`
- §3.9 — revise — ambiguity — payments returns HTTP 201 with the ledger entry, carrying the submitted `effective_date` and a null `source_entity_id` — `routes/licensees.py:285-288`

Left alone in Pass 1: bond-requirement/average-liability/risk-score formulas, `bond-status`/`risk-profile` field sets, certificate validity's six conditions, issuance check order, revocation cascade, bond supersede/release ordering, terminal registration/`ERR_DUPLICATE_TCN`, §2.11/§5 tables — impl already matches uniquely. Also left unpinned: Flask's fallbacks for unknown paths/methods/unparseable JSON (no declared endpoint exercises them), unbounded terminal `name`, unstored `reason` on licensee suspend/revoke.

### Pass 2 — removals, returns, cross-matching (14 ambiguity-pins, 3 mismatch-revisions)
- §3.3 ¶218 — insert — ambiguity — a `RackRemoval` is not a §2.1-owned resource, so single read and list are not scope-narrowed for a `LicenseeAgent` — `routes/removals.py:141-162`
- §3.3 ¶222 — revise — **mismatch (Step 8 lead 1, CONFIRMED)** — replaced "the deferral branch … can always assume a fully bonded purchaser" with the actual gap: `would_defer` is gated on `certificate is None` but branch 4 tests only `GOVERNMENT`/`AGRICULTURE`, so a valid `EXPORT` certificate with `destination_state == "MN"` skips the bond test yet falls into branch 5 — `routes/removals.py:64-68, 87-99`. The condition in ¶222 was already exact; only the trailing consequence aside was wrong and only it was rewritten.
- §3.4 ¶241 — insert — ambiguity — body `licensee_id` scope-checked as band 3, ahead of existence and status; missing/non-string is band-4 — `routes/returns_bp.py:26-34`
- §3.4 ¶243 — insert — ambiguity — a draft's lateness/money fields all start at zero — `routes/returns_bp.py:60-68`
- §3.4 ¶245 — insert — ambiguity — schedules-of-a-return and lines-of-a-schedule reads are scope-checked against the path resource, not narrowed — `routes/returns_bp.py:132-141, 231-239`
- §3.4 ¶247 — insert — ambiguity — `total_gallons` must be a two-decimal quantity >= 0 (0.00 legal) — `routes/returns_bp.py:103`
- §3.4 ¶249 — insert — ambiguity — gallons with more than two decimals are quantized half up, not rejected — `shape.py:126-138`
- §3.4 ¶249 — insert — ambiguity — the `document_date`-in-period test needs the parent, so an unknown schedule yields `ERR_SCHEDULE_NOT_FOUND` even when the date is also out of period — `routes/returns_bp.py:166-175`
- §3.4 ¶251 — insert — ambiguity — "the line's product" is the parent schedule's `product_code` — `routes/returns_bp.py:188-190`
- §3.4 ¶255 — insert — ambiguity — a `SCH_6`/`SCH_7` line with no certificate reports `ERR_CERTIFICATE_NOT_VALID_ON_DATE` at filing, not a shape error — `routes/returns_bp.py:309-313`
- §3.5 ¶281 — insert — **mismatch** — opening an amendment does not re-test the filer's revocation — `routes/returns_bp.py:400-433`
- §3.1 ¶186 — revise — **mismatch (widening a Pass-1 paragraph)** — narrowed "no new returns" so it no longer contradicts the amendment behaviour; Pass 1's revoked-vs-state-invalid sentence untouched
- §3.6 ¶289 — insert — ambiguity — a supplied `tolerance_gallons` must be >= 0 — `routes/crossmatch.py:157`
- §3.6 ¶305 — insert — ambiguity — the auto-created case records `risk_score_variant` `VARIANCE_WEIGHTED` — `routes/crossmatch.py:147-149`
- §3.6 ¶307 — insert — ambiguity — `response_due_date` is any well-formed date, never required to be in the future — `routes/crossmatch.py:234`
- §3.6 ¶309 — insert — ambiguity — `referenced_return_id` is a band-7 FK: unknown → `ERR_RETURN_NOT_FOUND`, ahead of the `INQUIRY_SENT` state check — `routes/crossmatch.py:259-263`
- §3.6 ¶314 — insert — ambiguity — `write_off_reason` is stored but never serialized — `routes/crossmatch.py:299` vs `services/derive.py:371-390`
- §3.6 ¶317 — revise — **mismatch (Step 8 lead 2, CONFIRMED)** — licensee-level `unreported_gallons_total` excludes only `WRITTEN_OFF`/`RESOLVED_EXPLAINED`, so an escalated variance stays in it (¶317 had also contradicted ¶367, which was already correct); also pinned that only a `MATCH_VARIANCE` return advances and that a `MISSING_COUNTERPARTY_RETURN` row has a null `distributor_return_id` — `services/derive.py:155-162`, `routes/crossmatch.py:314-325`

Left alone in Pass 2: the rack-imposition ladder and step-three money rules, `_compute_tax` / per-product floor / one-rounding-per-product / `days_late` / interest / penalty tier + surcharge / `total_remittance_cents` / amendment copy rule, filing's seven guards and their order and ledger postings, cross-match cell enumeration and the four run counters and conservation law and the escalate-vs-skip asymmetry, §4/§5 rows for those endpoints — all already pinned uniquely. Licensee counters PRD calls "incremented" are derived on read (observationally identical, covered by Pass 1's §2.4 language).

### Pass 3 — refunds, roadside, audits (17 ambiguity-pins, 5 mismatch-revisions)
- §3.6 ¶315 — insert — ambiguity — hand-driven `ESCALATE_TO_AUDIT` records `risk_score_variant` `VARIANCE_WEIGHTED` and `selection_score` 0 — `services/cascade.py:118-140`
- §3.7 ¶321 — insert — ambiguity — body `licensee_id` scope-checked at band 3 before the band-6 read, only when present and a non-empty string — `routes/refunds.py:60-63`
- §3.7 ¶321 — insert — ambiguity — `equipment_class`: explicit `null` accepted on a non-PTO claim, any non-null value on a non-PTO claim is band-4, band 4 on PTO requires only a non-empty string, enum membership is the separate band-13 test — `routes/refunds.py:68-73, 89-90`
- §3.7 ¶323 — revise — ambiguity — filing gate order pinned: `ERR_LICENSEE_REVOKED` (9) → `ERR_REFUND_BLOCKED_BY_AUDIT` (10) → `ERR_REFUND_PERIOD_NOT_FILED` (12) → `ERR_EQUIPMENT_CLASS_INVALID` (13) → `ERR_REFUND_EXCEEDS_TAX_PAID` (14) — `routes/refunds.py:76-103`
- §3.7 ¶323 — revise — **mismatch** — only a PTO claim consults `equipment_class`; the reefer factor-of-ten rejection is **strictly greater** than 15000.00 (exactly 15000.00 passes and is merely clamped) — `routes/refunds.py:36-38, 91-94`
- §3.7 ¶331 — insert — ambiguity — `recommended_gallons` optional on APPROVE/DENY, recorded verbatim when supplied (null when omitted); the `allowable_gallons` ceiling test runs after the SUBMITTED state test — `routes/refunds.py:154-168`
- §3.7 ¶337 — revise — **mismatch** — "DENIED is the one path by which pool capacity is recovered" was wrong: the waterfall reads each surviving claim's current `allowable_gallons`, so a `PARTIALLY_APPROVED` reduction frees the difference too — `routes/refunds.py:42-53, 204-205`
- §3.8 ¶347 — insert — ambiguity — a REVOKED licensee's POSITIVE test still returns 201 at `RECORDED` with `prior_positive_count`/`penalty_cents` 0, no ledger row, no cascade; no other licensee status is consulted; inspections are not scope-narrowed — `routes/roadside.py:63-72`
- §3.8 ¶355 — insert — ambiguity — hop one is part of creating the inspection, so the created row returns `version` 1 with `updated_at` equal to `created_at`; the licensee row is not written at that hop — `routes/roadside.py:55-81`
- §3.8 ¶357 — insert — ambiguity — dismissal persists the reason as `dismissal_reason` (null until then) and advances the inspection's `version` to 2 — `routes/roadside.py:124-126`
- §3.9 ¶369 — insert — ambiguity — reversed months are `ERR_DATE_RANGE_INVALID` before the overlap rule; equal start/end is legal; the subject's `status` is never consulted — `routes/audits.py:56-61`
- §3.9 ¶371 — insert — ambiguity — under a non-`RISK_SCORE` method the variant is ignored for scoring but still stored verbatim — `routes/audits.py:41-43, 63-75`
- §3.9 ¶375 — revise — **mismatch** — buffered-window comparison is **inclusive** after widening both ends (`a_lo <= b_hi and b_lo <= a_hi`), not half-open; observable at exact abutment — `services/cascade.py buffered_overlap`
- §3.9 ¶377 — insert — ambiguity — a fresh case carries `additional_tax_cents`, `assessment_penalty_cents`, `assessment_interest_cents`/`assessed_total_cents` at 0 — `services/cascade.py:118-140`
- §3.9 ¶377 — insert — ambiguity — the case's owning licensee for scope purposes is `subject_licensee_id`, and agent list reads are narrowed by it — `routes/audits.py:28-29, 91`
- §3.9 ¶379 — insert — ambiguity — a `to_status` outside the five case statuses is band-4; a CLOSED case refuses advance, assessment, abatement, protest and finalization with `ERR_AUDIT_CASE_STATE_INVALID` (409), and that test precedes every `assessment_status` test — `routes/audits.py:106-111, 142-143, 178-179, 207-208, 226-227`
- §3.9 ¶383 — insert — ambiguity — issuance guards run closed-case → already-issued → `case_status` → segregation, so a closed case bearing a FINAL assessment reports `ERR_AUDIT_CASE_STATE_INVALID` — `routes/audits.py:142-150`
- §3.9 ¶387 — insert — ambiguity — the `ASSESSMENT` ledger row is appended unconditionally, even when `additional_tax_cents` is 0 — `routes/audits.py:164-167`
- §3.9 ¶389 — insert — ambiguity — protest is legal from `ISSUED` only, finalize takes no body fields and has no segregation rule, wrong status is 409 — `routes/audits.py:209-210, 220-229`
- §3.9 ¶391 — insert/revise — ambiguity — abatement legal from `ISSUED` or `PROTESTED` and no other status, and its **four** guards run closed-case → `assessment_status` → segregation → balance — `routes/audits.py:178-188`
- §2.4 ¶87 — revise — **mismatch** — original text said `version` increments on "mutations that only touch computed fields"; widened (not reverted): computed fields are re-derived on read, so a licensee whose `balance_cents`/counters move because a row elsewhere was written does not advance its own `version` — `routes/refunds.py:232-234`, `routes/roadside.py:78-81`, `routes/audits.py:164-167, 193-195`
- §2.9 ¶127 — revise — **mismatch** — Pass-1 wording "every affected row is mutated in full … its `version`" over-promised; softened to "every affected row **the server writes**", plus a clause that a row the cascade does not write keeps its `version`
- §2.1 ¶19 — insert — ambiguity — owning-FK enumeration extended with `subject_licensee_id` for `AuditCase` — `routes/audits.py:28-29`

Verdicts on the eight impl-generator-flagged choices: (1) refund gate ordering — newly pinned; (2) `equipment_class` band split + reefer boundary — codes already named, band split/null-acceptance/strictly-greater newly pinned; (3) abate from ISSUED-or-PROTESTED vs protest ISSUED-only — legal-from sets already pinned, refusal code and guard order newly pinned; (4) CLOSED-case and wrong-`assessment_status` → 409 — newly pinned; (5) issuance check order — newly pinned; (6) POSITIVE inspection `version` 1 — newly pinned; (7) REVOKED licensee POSITIVE test — newly pinned; (8) cascade-created case variant/score — already pinned for auto-escalation, newly pinned for hand-driven escalate.

**Pass 3's final whole-document consistency read** covered all 23 sections and fixed three cross-pass/original contradictions (§2.4 ¶87 and §2.9 ¶127 `version`-on-computed-fields, §3.9 ¶375 "half-open") plus one of its own slips ("three abatement guards" → four). Re-verified consistent: ¶19 vs ¶377 owning FKs, §2.8 ledger entry types vs the REFUND/PENALTY/PENALTY_REVERSAL/ASSESSMENT/ABATEMENT rows, the §2.11 band ladder vs the newly pinned orderings, §3.1 ¶186 revocation cascade vs §3.7 DENIED semantics, §3.9 ¶363-367 risk scoring vs `calc.risk_scores`, ¶393 payment `version` vs the §2.4 widening.

Left unpinned by design: within-band-4 field evaluation order (unpinned everywhere in the PRD; pinning it in one section only would be locally inconsistent) and ledger memo strings (§2.8 already treats memo as free text).

### Step 9 totals and orchestrator verification
44 ambiguity-pins + 11 mismatch-revisions across the three passes. `PRD_COMPLETED.md`: 546 lines / 126057 bytes vs `PRD_FINALIZED.md`'s 546 / 110873 — **+15068 chars, 51 paragraphs revised (102 diff lines), NOT byte-identical**, so the scan demonstrably ran. Structure intact: 5 top-level sections, 62 endpoint rows, 75 `ERR_` rows, ends on a complete table row (`| ERR_PAYMENT_EXCEEDS_BALANCE | 422 |`) at a real boundary — no truncation. Every edit was in-paragraph; no sections added or removed. Confirmed 0 files under `workspace/implementation/`, `test_suite/`, or `test_helpers/` were modified after the 13:40 green sweep, so the 8/8 × 99-test result still describes the shipped artifacts exactly.

**PIPELINE COMPLETE.**
