## Step 1: Create task directory — 2026-09-04T08:26:22.149831775Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2698_superfund_site_remediation_responsible_party_allocation and its workspace/ subdirectory (pre-assigned path from the entrance invocation; no index auto-allocation performed).


## Step 2: Generate scaffold — 2026-09-04T10:16:06.78866297Z

All three scaffold artifacts are complete and the lint is clean.

**Files** (in `/home/ubuntu/github/CodingPRD/tasks/task_2698_superfund_site_remediation_responsible_party_allocation/`)
- `SCAFFOLD.yaml` — 3158 lines, §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2259 lines, single top key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4122 lines, single top key `scaffold_corner_design`

**§1.0–§1.7 counts:** 14 entities, 12 state machines, 2 OCC concurrency rules (`expected_site_version` on `POST /sites/{id}/allocation-rounds`, `expected_prp_version` on `POST /sites/{id}/cost-recovery-actions`), 14 calculations, 41 priority-ordered validations, 67 endpoints, 49 error codes, 6 roles (`segregation_of_duties` role model with two entity-backed identities). Profile: multi_party_negotiation / ledger_reconciliation, graph topology, cyclic state machines, layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation, selector_policy; `expert_plus`.

**§1.8 (difficulty):** 9 rule blocks × 2 instances = 18, covering dual-variant divergence (provisional/final shares, central-tendency/RME risk), precision (per-term NPV rounding, pre-fee oversight tier keying), cyclic/parallel state shape, two three-hop cascades, two priority-pair conflicts, two inclusive boundaries, two cross-entity state gates, two temporal-overlap rules (chain-of-title, buffered work windows), and two compensation/identity-restoration instances.

**§1.9 (corner breadth audit):** 81 instances across all nine guide sections — entities 9, state_machines 9, calculations 17, validations 9, endpoints 6, errors 20, rbac 5, cross_cutting_complexity_layers 5, consistency_model 1. 48 carry full 7-clause recipes; 33 are `excluded_because` stubs citing a real §1.8 instance by name (no `test_recipe`). Coverage notes: a 49-line roll-call comment maps every error code to the instance that raises it (verified programmatically: all 49 codes appear, none orphaned); both OCC rules get real stale-version instances that re-read and retry; the guide's "Bulk action" endpoint row and the out-of-taxonomy `selector_policy` layer are documented as YAML comments explaining why no instance exists / where they are exercised instead.

**Verification performed:** `scaffold_lint.py` → `VERDICT: clean lint` (67 endpoints, 14 entities, 18 §1.8 + 48 §1.9 instances, 984 calls scanned, all FKs reverse-reachable). Two lint/consistency defects were found and fixed in this pass: an undeclared `rejection_reason` payload key on the verification endpoint (→ `verification_note`), and two bad grounds references (`calculations.party_volumetric_profile`, `calculations.oversight_cost_assessment`). The immediate-consistency instance's oversight arithmetic was also corrected — a cumulative direct subtotal of 9,000,000 crosses `TIER1_CEILING_CENTS` and re-rates the whole subtotal at 1275 bp (indirect 1,147,500, billed 10,147,500), not per-posting tier-1 rating. Additional independent checks: all instance names unique across both design files, every `${var}` bound by an earlier `captures:`, all grounds resolve, no dangling instance names in comments, and all three files parse under PyYAML with tails at real structural boundaries.

## Step 3: Copy shared files — 2026-09-04T10:16:06.97875758Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-04T10:36:33.344952068Z

PRD generation is complete.

## Output
`workspace/PRD.md` — 536 lines, 107,754 bytes. Written in 15 incremental `cat >>` appends (never a single Write), `wc -l` verified after each. File ends at a real boundary: the last row of the completed §5 error table.

## Section list
- `# Superfund Remediation Allocation API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 11 subsections: 2.1 Actors/Headers/RBAC · 2.2 API Response Structure (verbatim fixed block, verified byte-present) · 2.3 Pagination, Filtering, List Ordering · 2.4 Identifiers, Timestamps, Record Versioning · 2.5 The Logical Clock · 2.6 Path Resolution and Validation Precedence · 2.7 Stale-Version Guards · 2.8 Money, Basis Points, Rounding · 2.9 The Cost Posture Gate · 2.10 The Response-Cost Conservation Ledger · 2.11 Segregation of Duties and Facilitator Neutrality
- `## 3. Business Logic & Workflows` — 9 subsections: 3.1 Site listing + party roster · 3.2 Chain of title + waste-in verification · 3.3 RI, sampling, risk characterisation · 3.4 Feasibility alternatives, NPV, remedy scoring · 3.5 Record of Decision, community involvement, signature · 3.6 Allocation rounds, Gore-factor weighting, balloting, adoption · 3.7 Settlement instruments, oversight billing, stipulated penalties · 3.8 Procurement, field work, construction completion, long-term stewardship · 3.9 Cost recovery, contribution claims, de minimis settlements
- `## 4. API Endpoint Reference` — 4-column table, 67 rows
- `## 5. Error Codes` — 2-column table, 49 rows

## Hard Contract reports
**Contract 1 — Field-Name Coverage: PASS (2 independent passes).** Pass 1 against a pre-computed 176-identifier set: 0 missing. Pass 2 against a set rebuilt from scratch by YAML-parsing the scaffold (174 `entities[].fields[].name` + 98 endpoint `input` identifiers → 177 unique): 0 missing. All values are backtick-quoted. Additionally ran an inverse "invention detector": every backticked identifier in the PRD also occurs in SCAFFOLD.yaml, with the single exception of `updated_at`, which the skill mandates as a common resource property.

**Contract 2 — Rule Coverage: PASS.** All 41 `validations` are present in §2.6 in scaffold order with their error identifiers and `applies_to` scopes; all 49 error ids appear in §1–§3 prose (not only in §5). Both `concurrency_rules` (OCC on round creation and recovery-action creation) are in §2.7 with the "no state precondition would stop the create" rationale. All 12 state machines / 57 transitions are covered — mechanically checked that every declared state token appears; the 21 transitions not expressed as a literal `FROM → TO` arrow were each hand-verified as covered in prose (cost_posture derivation in §2.9, the OM_PHASE self-loop, DELETED_FROM_NPL retirement, ORPHAN/ORPHANED, SETTLED/DE_MINIMIS_SETTLED and their reversals, WITHDRAWN, PENDING, FAILED→DRAFTING, CONSTRUCTION_COMPLETE→CLOSED, ACCEPTED→COLLECTED). All 14 calculations are described including both dual-variant ones (provisional vs final allocation arithmetic; central-tendency vs RME risk). All enum values of every enum field appear (0 missing). Cross-entity side effects are written as explicit numbered hops for the three cascades (waste-in verification, defunct party, NOT_PROTECTIVE five-year review), and sibling-branch symmetry is stated for reopening-from-balloting vs from-failure, VERIFIED vs REJECTED, and the void-a-de-minimis vs void-a-demand asymmetry.

**Contract 3 — §3 Path Purity: PASS.** 338 distinct backtick tokens in §3; 0 start with `/`, 0 are a bare HTTP method, 0 combine method+path. The only slash-bearing token outside §4 is in §2.6, where it legitimately illustrates left-to-right nested path resolution.

## Coverage notes / corrections made during verification
- §4's endpoint table was diffed set-wise against the scaffold: the 67 `(method, path)` pairs match exactly, and the 49 error rows match the scaffold catalogue exactly.
- Fixed two invented identifiers found by the inverse detector: `participation_status` → `status` (the real PRP field) and `verification_status` → `status` (the real query param).
- Corrected 11 §4 filter claims to match each endpoint's actual `input` list (added `status`/`legal_status`/`disposition`/`qa_status`+`medium`/`activity_type` where missing, removed non-existent `ballot`, `toxicity_class`, `medium`, `de_minimis_eligible` filters).
- Rewrote the closing paragraph of §2.9: the earlier draft wrongly claimed a frozen site's contract award is caught by the restriction check. It now states that the frozen condition is *not* a subset of the four restriction triggers, that award's own precondition bars both postures, and that a frozen-site award reports `ERR_SITE_COST_FROZEN`.
- Removed a §3.7 promise of a "reverse view … as a read on the party" for `party_prp_ids`; that reverse lookup is mentioned in a scaffold field description but is not one of the 67 endpoints, so it would have contradicted §4.
- Constraint honoured: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced, and no sibling task directory was read.

**Orchestrator truncation check:** verified independently — 536 lines, all 5 top-level sections + 11 §2 subsections + 9 §3 subsections present, tail ends on a complete §5 table row (`| `ERR_PENALTY_BALANCE_MISMATCH` | 422 |`), not mid-sentence. Not truncated; no regeneration needed.

## Step 5: Generate unit tests — 2026-09-04T12:06:28.261306419Z

Suite is complete and verified.

## Output (both at the task root, nothing written under `workspace/`)

`test_helpers/` — 9 modules (`__init__`, `api_client`, `api_errors`, `assertions`, `constants`, `factories`, `fixtures`, `test_users`, `types`).

`test_suite/` — `conftest.py` + 18 test modules, **142 tests**:

| file | tests | source |
|---|---|---|
| test_01_dual_variant_calc | 7 | queue A |
| test_02_combinatorial_formula | 7 | queue A |
| test_03_non_linear_state_machine | 9 | queue A |
| test_04_transitive_cascade | 7 | queue A |
| test_05_priority_pair_validation_conflict | 6 | queue A |
| test_06_boundary_precision_check | 8 | queue A |
| test_07_cross_entity_state_dependency | 6 | queue A |
| test_08_resource_temporal_overlap | 8 | queue A |
| test_09_compensating_invariant | 9 | queue A |
| test_10_corner_entities | 7 | entities |
| test_11_corner_state_machines | 10 | state_machines |
| test_12_corner_calculations | 10 | calculations |
| test_13_corner_validations | 9 | validations |
| test_14_corner_endpoints | 7 | endpoints |
| test_15_corner_errors | 19 | errors |
| test_16_corner_rbac | 8 | rbac |
| test_17_corner_cross_cutting | 3 | cross_cutting_complexity_layers |
| test_18_corner_consistency_model | 2 | consistency_model |

## Coverage

- **Queue A (§1.8): 18/18 live instances translated.**
- **Queue B (§1.9): 46/48 live instances translated** (31 stub entries carrying `excluded_because:` correctly ignored).
- Verified mechanically: every non-stub instance name in either yaml appears as a `Design:` tag; every test has exactly one `Design:` line and exactly one `PRD: "..."` quote that is a literal substring of `workspace/PRD.md`; no dangling tags (`TOTAL tests: 142 problems: 0`). All files `py_compile` clean, `pyflakes` clean (only the intentional re-export warnings in `test_helpers/assertions.py`/`fixtures.py` and the `conftest` star-import remain), and `pytest --collect-only` collects all 142 with no errors.

## Skipped instances (2, gaps left as gaps)

1. `Corner/endpoints/corner_rod_can_only_cite_an_investigation_of_its_own_site_not_found` — no PRD sentence requires a ROD's cited `remedial_investigation_id` to belong to the path site; the PRD's own cross-entity-ownership pattern is a 409 `ERR_ALTERNATIVE_NOT_FOR_SITE`-style gate, contradicting the design's 404.
2. `Corner/cross_cutting_complexity_layers/corner_derived_party_totals_reconcile_after_add_verify_and_reject` — three of its six assertions contradict PRD line 234 (and SCAFFOLD.yaml's own field list): it asserts a party-level `effective_volume_tons` field that does not exist (the party has `submitted_volume_tons`/`verified_volume_tons`), asserts `volumetric_share_pct` 93.33/6.67 after adding an *unverified* record when the PRD derives that percentage from **verified** volumes only (83.33/16.67), and asserts `max_toxicity_class == I` from an unverified record when the PRD derives it across verified records only.

## Two PRD-vs-design deviations inside translated instances

- `ERR_SEGREGATION_OF_DUTIES`: the design text says HTTP 403; PRD line 194 and the §5 table (line 512) say **409**. Tests assert the `error_id` only and let the registered status map govern.
- `Corner/rbac/corner_approver_cannot_sign_the_rod_returns_4XX`: the design also asserts the ROD *author* (rpm-001) is refused at signature. PRD line 194/282 bars only the cited investigation's `approved_by_user_id`, so that one assertion was omitted; the approver refusal, the untouched-state checks (`public_comments_count == 1`, so the refusal is the duties rule and not `ERR_COMMUNITY_INVOLVEMENT_INCOMPLETE`) and the rpm-003 success all translate.

**Orchestrator check:** confirmed `test_helpers/` and `test_suite/` are at the task root; no stray copies under `workspace/`.

## Step 6: Generate implementation — 2026-09-04T12:06:28.268033414Z

Implementation complete for `task_2698_superfund_site_remediation_responsible_party_allocation`.

## Modules written
`workspace/implementation/` — 4,135 lines across 24 files, all written in chunked `cat >>`/`cat >` appends, all parse and compile.

- **Boot**: `start.sh` (reads `$PORT`, guarded pip, `exec python3 app.py` in foreground), `requirements.txt` (`Flask>=2.2`), `app.py` (factory, 10 blueprints, `ApiError`/`HTTPException`/`Exception` handlers, `host=0.0.0.0`).
- **Foundation**: `constants.py`, `errors.py` (49 error IDs → HTTP), `numeric.py` (exact ROUND_HALF_UP over `Fraction`, never float), `logical_clock.py` (starts `2026-08-01T00:00:00Z`, never falls back to wall clock), `store.py` (14 entity dicts + oversight-posting audit trail, all empty at boot — **no seeding of any kind**), `envelope.py`, `authz.py`, `shape.py`, `txn.py` (snapshot-diff single version bump + `force()` for the two spec-mandated no-field-change bumps), `calc.py` (all 14 calculations), `serialize.py` (scaffold field order; the 3 immutable types carry only `id`/`created_at`), `derive.py` (all derived fields, the ledger, posture cascade, the three multi-hop cascades).
- **Routes** (`routes/`): `reads.py` (30 GETs), `sites.py`, `prps.py`, `evidence.py`, `ri.py`, `rod.py`, `rounds.py`, `decrees.py`, `contracts.py`, `actions.py`, `common.py`.

## Coverage
- **67/67 endpoints** registered (verified against the URL map: 30 GET + 37 POST, matching the 67 scaffold `path:` entries).
- **41/41 validations** wired in the PRD §2.6 precedence order (pagination/filters before 404s; OCC before posture; posture before state; fiscal checks last).
- **14/14 calculations**, including both dual-variant ones (provisional/final allocation, central-tendency/RME risk), per-term NPV rounding, 3-tier oversight re-rating on the pre-fee subtotal, penalty accrual recomputed from scratch each assessment, de minimis premium floor frozen at offer.
- **12/12 state machines**, both independent decree dimensions, all three cascades, and the void-and-restore compensations.

## Smoke test
Launched `PORT=18742 bash start.sh`, ran two end-to-end scripts (~110 requests) then killed the server by PID resolved from the port (`ss -ltnp`), port confirmed free. **0 failures**, with hard asserts on: NPV `1,808,406,854`; oversight tier `(1550, 5,313,000)`; penalty `(30 days, 3,000,000, not capped)` then a repeat assessment recomputing to `(40, 4,500,000)` not adding; ownership days `5,936`; EPC mean `40.000` with `action_level_exceeded` true; ledger identity and the `allocated+orphan+settled == 100.00` share identity holding after adoption, defunct-orphan, de-minimis settle, and both voids; failed-round → reopen → adopt cycle; RESTRICTED→FROZEN→OPEN posture transitions; five-year-review `NOT_PROTECTIVE` 3-hop cascade with the due date chaining off the previous due date (`2031-10-20` → `2036-10-19`); 401/403/404/409/412/422 error shapes.

Two smoke-script bugs of my own (wrong enum literal, a de-minimis fixture whose 4% share was legitimately ineligible) were fixed in the script, not the implementation — no implementation defect was found.

## Step 7: Run tests and iterate — 2026-09-04T12:38:02.735736097Z

**Exit clean: all 8 rounds of the final sweep report 142/142 passed, 0 failed.**

## Summary

**Iterations run:** 2 full 8-round parallel sweeps (`setsid nohup`, per-round `results.$i.json`). Iteration 1: 103/142 in all 8 rounds, 39 deterministic failures, zero flakiness (all rounds identical). Iteration 2 (after the fixes below): 142/142 in all 8 rounds.

**Tests deleted:** none. One assertion removed under STEP 1c partial coverage:
- `test_suite/test_11_corner_state_machines.py` `TestDefunctPartyAutoAbstains` — dropped `assert is_iso8601_timestamp(share_b["ballot_cast_at"])`. BRANCH-ASYMMETRIC SIDE-EFFECT SILENCE: §3.1's defunct cascade enumerates exactly what it touches ("that party's share instead has its `ballot` stamped `ABSTAIN` … and the round's `balloted_count` and `accept_share_pct` are recomputed accordingly") and never mentions `ballot_cast_at`; §3.6's stamping sentence governs a party *casting* a ballot, not the cascade. Every other assertion in the test kept.

**Fixes to `test_helpers/`:**
- `factories.py` `remedy_alternative_payload` — default `discount_rate_bp` 10_000 → 2000, `capital_cost_cents` 970_000_000 → 938_888_889. §3.4: "the real `discount_rate_bp` in basis points (from 0 through 2000)"; the factory's own docstring already said 0–2000. Capital rebalanced so `npv_cents` stays exactly 1,000,000,000 and every dependent `cost_score`/`remedy_score` assertion is untouched.
- `fixtures.py` `add_alternative` defaults — same substitution, same reason.
- `fixtures.py` `build_construction_chain` default alternative dict — same substitution, same reason.

**Fixes to `test_suite/`** (STEP 2, PRD-inconsistent preconditions):
- `test_08_resource_temporal_overlap.py` — `activity_type` values `EXCAVATION`/`HAULING`/`MONITORING`/`MAINTENANCE` → `CONSTRUCTION`/`CONSTRUCTION`/`LONG_TERM_MONITORING`/`MAINTENANCE_SHUTDOWN` (§3.8 enum). No assertion reads `activity_type`.
- `test_12_corner_calculations.py` — `_wrenfield_mixed_record_states` `evidence_grade="D"` → `"C"` (§3.2 enum is `A`,`B`,`C`); `_rushmere_two_alternatives` rate → 2000 with capitals 938_888_889 / 2_438_888_889, preserving the asserted npv 1e9 / 2.5e9.
- `test_13_corner_validations.py`, `test_15_corner_errors.py` (3 fixtures), `test_16_corner_rbac.py` (3 call sites) — same rate/capital substitution.
- `test_15_corner_errors.py` `TestSiteListingPhaseGate` — removed `issue_notice` + `record_election` from a still-`PROPOSED` site's setup; §3.1 permits notice only when "`listing_status` is neither `PROPOSED` nor `DELETED_FROM_NPL`", so the setup itself was being (correctly) refused.
- `test_15_corner_errors.py` `_marrow_bend_adopted_with_an_orphan` — added the third `cast_ballot(..., prp_c, "ACCEPT")`. The fixture stopped at 2 of 3 shares, so §3.6's "The round resolves itself on the ballot that makes `balloted_count` equal `share_count`" never fired and the round stayed `BALLOTING`; the defunct cascade does not adopt a round. All three tests' figures (A 97.31, allocated 98.01, orphan 1.99, ledger 4,620,000/4,528,062/91,938/0) reproduce exactly.
- `test_07_cross_entity_state_dependency.py` — round fields now read via `read_round(...)` instead of the ballot POST's response body. The PRD never says the ballots endpoint returns the round (§2.2 "the created or updated resource" is ambiguous when a write touches both the share and its round), while `GET /allocation-rounds/{id}` is documented as exposing exactly those fields. No assertion weakened.

**Fixes to `workspace/implementation/`:**
- `routes/decrees.py` `compliance_event` — `effective_at` parsed as an ISO-8601 instant (`shape.datetime_field`) rather than a bare calendar date; `first_noncompliance_date` and the accrual window now use its date part. §3.7 stamps `first_noncompliance_date` **from** the event's `effective_at` but `last_assessment_at` **with** it, and every other `_at` field in the PRD is an instant (`created_at`, `collected_at`, `start_at`, `lodged_at`, …) while date-valued fields are named `_date`/`_on`/`_deadline`. This one bug caused 12 failures across test_03/05/12/15.
- `serialize.py` — `last_assessment_at` projected as a timestamp (`DT`) not a day, per §3.7 "Every assessment stamps `last_assessment_at` with its own `effective_at`".
- `derive.py` `recompute_ledger` — `recovered_cost_cents` now sums `received_cents` over `ACCEPTED` as well as `COLLECTED` actions. §3.9: "Every receipt increases the site's `recovered_cost_cents` … so the ledger identity of §2.10 holds after every partial payment, not merely at the end"; a partial receipt sits on an action that is still `ACCEPTED`, and voiding zeroes `received_cents` so nothing double-counts.

No entity data is seeded at startup, storage remains in-memory only, no report/summary files were written, and `worklog.md` was not touched.

**Orchestrator verification (independent of the subagent's claim):** read all 8 `workspace/implementation/results.$i.json` directly — each reports `passed=142, failed=0, total=142, errors=0, skipped=0`, all 8 files present and ~50 KB, written at the same timestamp (12:30). Sweep artifacts confirmed real; Step 8 is NOT skipped (3 `implementation/` fixes present in the diff).

## Step 8: Finalize PRD — 2026-09-04T12:49:22.877100481Z

## Line counts
- `PRD.md`: 536 lines / 107,365 chars → `PRD_FINALIZED.md`: 536 lines / 109,307 chars (**+1.81 %** by character; every patch is inline inside an existing paragraph, so line count is unchanged). Tail verified: file still ends at the §5 error-code table with `| ERR_PENALTY_BALANCE_MISMATCH | 422 |`.

## Changes (7 edits, 5 PRD locations)
- **§2.10 (ledger)** — revise — `recovered_cost_cents` now sums `received_cents` over actions whose `status` is `ACCEPTED` **or** `COLLECTED` (partial receipt sits on an `ACCEPTED` action), with the void/zero note kept and other statuses noted as receipt-free — `derive.py:411-418`.
- **§3.1 (defunct cascade)** — insert — the `ABSTAIN` stamp writes nothing else on the share (`ballot_cast_at`, `ballot_rationale` left as-is), and the cascade never resolves the round even when `balloted_count` reaches `share_count` — `derive.py:519-539` (esp. 536-538).
- **§3.6 (balloting)** — insert — the ballots endpoint returns the **allocation share** in `data`, never the round; round counters/status/totals are read from `GET /allocation-rounds/{id}` — `routes/rounds.py:170`.
- **§3.7 (compliance event inputs)** — revise — `effective_at` is an ISO-8601 UTC instant like every other client-supplied `_at` field, not a bare date (a value with no time component reads as midnight UTC) — `routes/decrees.py:131-132`, `shape.py:149-158`, `logical_clock.py:12-25`.
- **§3.7 (VIOLATION)** — revise — `first_noncompliance_date` is stamped from the **date part** of `effective_at` because it is a plain calendar date — `routes/decrees.py:147`, `serialize.py:211`.
- **§3.7 (PENALTY_ASSESSMENT)** — revise — first-assessment precondition compares the **date part** vs `first_noncompliance_date`; the self-loop compares **full instants** vs `last_assessment_at`; `last_assessment_at` is projected as a timestamp while `first_noncompliance_date` is a date — `routes/decrees.py:151-157,172`, `serialize.py:211,221`.
- **§3.7 (accrual)** — revise — `days_in_violation` runs through the **date part** of `effective_at`; time of day never changes the window — `calc.py:124-135`, `routes/decrees.py:160-165`.

## Per-edit pre-edit search log
1. **Subject: `recovered_cost_cents` composition.** Enumerated: `derive.recompute_ledger` (only writer), its caller `recompute_site_derived`, `cost_ledger_view` (reads the stored field), and every action status producer — `create_action` (`OFFERED`, supersede→`SUPERSEDED`), `respond_action` (`REJECTED`/`ACCEPTED`, receipts still 0), `collect_action` (partial stays `ACCEPTED`, full→`COLLECTED`), `void_action` (`VOIDED` + `received_cents=0`). (c) Added "an action in any other status has never booked a receipt" so the sentence stays true for `OFFERED`/`SUPERSEDED`/`REJECTED`, and kept §3.9's existing per-receipt sentence untouched.
2. **Subject: what the defunct cascade writes on a share / whether it resolves a round.** Enumerated every writer of `ballot`/`ballot_cast_at`/`ballot_rationale`: `_mint_share` (rounds.py:47-62, all three null), `cast_ballot` (rounds.py:157-170, the only resolver), `reopen_round` (rounds.py:183-187, clears all three), `derive.defunct_cascade` (536-538, sets `ballot` only), `recompute_round_counters` (294-303), `adopt_round` (333-358). (c) Widened from "stay empty" to "left exactly as they were … a share whose party had already voted keeps the instant and the rationale of that earlier ballot", because a `BALLOTING` share may already carry both when its party is orphaned.
3. **Subject: response body of a write that touches two entities.** Enumerated all 40 POST handlers' `common.respond` targets: every other handler returns the resource its path names or the child it creates; only `/allocation-rounds/{id}/ballots` returns a child of the path-named parent. (c) Scoped the sentence to the ballots operation only rather than stating a general §2.2 rule, so `POST /sites/{id}/oversight-costs` (returns the site) and `POST /records-of-decision/{id}/public-comments` (returns the document) are not mis-described.
4. **Subject: type of the client-supplied `effective_at`.** Enumerated every `shape.date_field` vs `shape.datetime_field` call site: instants — `effective_at`, `collected_at`, `start_at`, `end_at`, `current_utc`; dates — `performance_deadline`, `start_date`, `end_date`, `incurred_on`. Also read `logical_clock._parse_instant` (accepts a bare date, coerced to midnight). (c) Qualified the universal as "every other **client-supplied** `_at` field", and added the midnight-UTC leniency instead of asserting a time component is mandatory.
5. **Subject: `first_noncompliance_date` value and projection.** Enumerated all writers/readers: `compliance_event` VIOLATION (147, `effective_day`), CURE clear (182), `enter_decree` clear (114), create default (52), the assessment precondition (152), `calc.penalty_accrual` (124-135), `serialize.CONSENT_DECREE` (`DAY`, 211). (c) None — the "date part / plain calendar date" phrasing holds on every path, including the clears.
6. **Subject: assessment ordering preconditions and `last_assessment_at` granularity.** Enumerated `compliance_event` branches 151-159 and 172, the CURE clear at 183, create default 62, `serialize` line 221 (`DT`), and `common.state`. (c) Split the sentence into two explicitly different granularities (day-level vs instant-level) rather than one uniform rule, since the impl genuinely mixes them; avoided claiming the self-loop re-checks `first_noncompliance_date` (it does not).
7. **Subject: the accrual day count.** Enumerated `calc.penalty_accrual` (127 `(effective_date - first).days + 1`, negative floor at 129), its single call site `routes/decrees.py:160-165` passing `effective_day`, and `days_in_violation` writers/clears (169, 184, create default 53). (c) None; added only that time of day never affects the count.

## Step 7 items that needed **no** PRD edit
- `discount_rate_bp` 10 000→2000 and the rebalanced capitals: PRD §3.4 already pins "from 0 through 2000" and `shape.int_field(..., hi=2000)` matches — pure fixture bug.
- `activity_type` enum in test_08: §3.8 already lists exactly `CONSTRUCTION`/`LONG_TERM_MONITORING`/`MAINTENANCE_SHUTDOWN`.
- `evidence_grade` D→C: §3.2 already lists `A`,`B`,`C`.
- test_15 `TestSiteListingPhaseGate` setup and `_marrow_bend_adopted_with_an_orphan` third ballot: both were fixtures contradicting rules the PRD already determines; the only genuinely under-determined part of the latter is pinned by edit 2.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` → 14 changed lines (not byte-identical), tail still the final §5 table row. Step 8 output accepted.

## Step 9 plan — 2026-09-04T12:49:22.883715444Z

Step 9 is run as **three sequential module-partitioned passes** over one shared `PRD_COMPLETED.md` rather than a single agent scanning all 24 impl modules, because a one-agent full scan of an implementation this size reliably under-covers the later modules. Pass 1 does the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 must NOT `cp` (they inherit the file in place). Partition:
- Pass 1 — cross-cutting layer: `app.py`, `constants.py`, `errors.py`, `numeric.py`, `logical_clock.py`, `store.py`, `envelope.py`, `authz.py`, `shape.py`, `txn.py`, `calc.py`, `serialize.py`, `derive.py`.
- Pass 2 — intake/evidence/decision routes: `routes/common.py`, `routes/sites.py`, `routes/prps.py`, `routes/evidence.py`, `routes/ri.py`, `routes/rod.py`.
- Pass 3 — negotiation/execution/recovery routes + reads: `routes/rounds.py`, `routes/decrees.py`, `routes/contracts.py`, `routes/actions.py`, `routes/reads.py`.

## Step 9: Complete PRD — pass 1 of 3 (cross-cutting layer) — 2026-09-04T14:02:36.186304047Z

## Line counts / delta
- `PRD_FINALIZED.md` (source): **536 lines, 109,709 chars** → `PRD_COMPLETED.md`: **542 lines, 120,097 chars** — **+6 lines, +10,388 chars**, 13 diff hunks. Tail verified: still ends at the final §5 row `| ERR_PENALTY_BALANCE_MISMATCH | 422 |`.

## Counts
**19 ambiguity-pins, 5 mismatch-revisions** (24 changes; no new sections, no whole-paragraph rewrites)

## Changes
- §2.1 — insert — ambiguity — headers matched/recorded verbatim: exact case-sensitive role match, no trimming, whitespace-only `X-User-ID` is 401 — `authz.py:20-26`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + 20 upper-case alphanumerics — `envelope.py:14`
- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the **logical clock**, not wall-clock — `envelope.py:20`
- §2.2 — insert — ambiguity — every field the PRD calls "empty" is present and carries JSON `null`, never `""` and never 0 — `serialize.py:22`, `routes/sites.py:39-55`
- §2.3 — insert — ambiguity — `created_at` comes from a frozen logical clock, so ties are normal; every ordering and tie-break chain falls back last to server insertion order, never to `id` — `derive.py:24`, `store.py:38`
- §2.3 — insert — ambiguity — the `/sites` descending list places the *later*-created record first when tied on `created_at` and `name` — `reads.py:31-32`
- §2.3 — insert — ambiguity — non-integer `epa_region` is malformed; the three identifier filters are unvalidated, so an unknown id yields an empty page, not 404; filter→order→slice sequence and the exact `has_more` test — `shape.py:207-233`, `reads.py:341-347`, `envelope.py:38`
- §2.4 — insert — **mismatch** — `version` rises by exactly 1 *per request* however many hops touch the record; a recomputation that changes nothing bumps nothing; a refused request mutates nothing; the two forced bumps — `txn.py:62-68`
- §2.5 — insert — ambiguity — clock may move backwards; `current_utc` parsed like any instant; returns 200 with `data` = `{current_utc}` only — `logical_clock.py:12-25`, `routes/sites.py:162-169`
- §2.6 item 3 — insert — ambiguity — strict non-coercive typing, `null` counts as absent, undeclared fields ignored, absent/empty body reads as `{}`, non-object or invalid JSON → `ERR_INVALID_REQUEST` 422 — `shape.py:26-34`, `app.py:65-68`
- §2.8 — insert — ambiguity — non-money numbers are plain JSON numbers (so `100.00` renders `100.0`); a declared scale is a ceiling, not a requirement — `serialize.py:26`, `numeric.py:56`, `shape.py:108`
- §2.8 — insert — ambiguity — rounding is performed on exact rationals, never on a float approximation — `numeric.py:26-38`
- §2.9 — insert — ambiguity — posture travels with the whole derived block re-reconciled together after any write that could touch it; idempotent — `derive.py:447-457`
- §2.10 — insert — ambiguity — the ledger read is a 13-field projection, read back rather than recomputed; the three share percentages read `0.00` with no adopted round — `derive.py:460-485`
- §3.1 — revise — **mismatch** — `hrs_score` carries *at most* two decimals, not exactly two — `shape.py:108`, `routes/sites.py:31`
- §3.1 — insert — ambiguity — the defunct cascade's adopted-round hop fires only on a share still `ALLOCATED`; round totals are re-derived from dispositions, not incremented — `derive.py:524`, `derive.py:314-330`
- §3.6 — insert — ambiguity — degenerate zero-denominator case: every raw share is 0.00 and the full 100.00 residual lands on one party — `calc.py:195-208`
- §3.6 — insert — ambiguity — `ERR_NO_ALLOCATION_BASIS` is **not** re-applied at adoption — `derive.py:335-336`
- §3.6 — insert — ambiguity — a drafting re-derivation that loses the basis writes `provisional_pct` 0.00 rather than refusing the verification — `derive.py:290`
- §3.6 — revise — **mismatch** — at adoption only `ORPHAN` and `DE_MINIMIS_SETTLED` are carved out; **every** other share (incl. `NOTIFIED` and `SETTLED`) becomes `ALLOCATED` with a `final_pct` — `derive.py:341-351`
- §3.7 — insert — **mismatch** — a site with no posting has no tier: `oversight_indirect_rate_bp` reads 0, not the first-tier 1,550 — `derive.py:387-390`
- §3.7 — insert — ambiguity — "governing" is re-evaluated live, so after the instrument terminates `oversight_cap_utilization_pct` reverts to empty and the cap check stops applying — `derive.py:149-155`, `derive.py:396-402`
- §3.8 — revise — **mismatch** — the not-protective hop moves **every** `SIGNED` document to `AMENDMENT_REQUIRED`, not one — `derive.py:546-549`
- §5 — insert — ambiguity — off-catalogue `ERR_NOT_FOUND` (404 unrouted path / 405 wrong method) and `ERR_INTERNAL` (500); each id maps to exactly one status regardless of endpoint — `app.py:57-75`, `errors.py:12-62`

## Modules verified fully pinned
- **`errors.py`** — the id→status table matches §5 row-for-row, all 49 ids, no extras beyond the two documented.
- **`calc.py`** — all 14 calculations match PRD formula-for-formula; only the zero-denominator edge was unpinned.
- **`serialize.py`** — field sets align exactly with §3 prose; no undocumented field emitted, `seq` never leaks, the three immutable types correctly omit `updated_at`/`version`.
- **`numeric.py`, `store.py`, `authz.py`, `app.py`, `logical_clock.py`, `envelope.py`, `shape.py`, `txn.py`, `derive.py`** — walked exhaustively; everything not listed above already had a unique PRD reading.

Left for a route pass: the returned resource of `POST /sites/{id}/oversight-costs` (returns the **site**, 200) was PRD-silent.

## Step 9: Complete PRD — pass 2 of 3 (intake/evidence/decision routes) — 2026-09-04T14:02:36.186304047Z

## Size
before: 542 lines / 120,097 chars → after: 542 lines / 130,549 chars. All 28 edits were in-paragraph inserts/revisions — no new sections, line count unchanged. Tail still the final §5 row.

## Counts
**ambiguity-pins: 20, mismatch-revisions: 4**

## Changes
- §3.1 (site create) — insert — ambiguity — `oversight_cap_utilization_pct`, `adopted_round_id`, `construction_complete_at`, `five_year_review_due_at`, `last_five_year_review_at`, `last_protectiveness_determination` start **null** (not 0); site returned at 201 — `routes/sites.py:45-59`
- §3.1 (list-on-npl) — insert — ambiguity — `listing_reference` required non-empty; state check outranks the HRS check; returns the site at 200 with the derived block re-reconciled — `routes/sites.py:66-76`
- §3.1 (party roster) — **revise** — **mismatch** — "Against a listed site" → "Against the site": impl applies **no** phase gate to party creation, only `deny_deleted` — `routes/prps.py:29-30`
- §3.1 (party defaults) — insert — ambiguity — `notice_reference` empty; party at 201; only `DELETED_FROM_NPL` refuses — `routes/prps.py:32-50`
- §3.1 (notice) — insert — ambiguity — `notice_reference` is a required non-empty string — `routes/prps.py:57`
- §3.1 (election) — insert — ambiguity — `response_note` validated but not persisted — `routes/prps.py:76`
- §3.1 (election) — insert — ambiguity — the lodged/entered-decree brake reports `ERR_INVALID_STATE_TRANSITION`; election and notice both return the **party** at 200 — `routes/prps.py:88-98`
- §3.1 (defunct) — insert — ambiguity — `defunct_reason` required, not persisted; any other posture (incl. `IDENTIFIED`) → `ERR_INVALID_STATE_TRANSITION`; returns the **party** at 200 — `routes/prps.py:105-114`
- §3.2 (ownership period) — insert — ambiguity — required/optional split (`end_date` optional, stored empty); cross-site `prp_id` is `ERR_PRP_NOT_FOUND`; a reversed date pair is accepted and yields negative `ownership_days` — `routes/evidence.py:31-35, 42-64`
- §3.2 (overlap) — insert — ambiguity — phase gate outranks overlap; only side effects are `ownership_days_total` + drafting-round provisionals; returns the **period** at 201 with no `updated_at`/`version` — `routes/evidence.py:48-71`
- §3.2 (waste-in submission) — insert — **mismatch** — cross-site `prp_id` → `ERR_PRP_NOT_FOUND`; `transporter_name`/`verified_*` defaults; **submission re-derives drafting-round provisionals**; verified-side figures unmoved; record at 201 — `routes/evidence.py:83-106`
- §3.2 (verification) — insert — ambiguity — a *missing* figure also reports `ERR_VERIFIED_VOLUME_EXCEEDS_CLAIM`; the only shape rule on `verified_volume_tons` is scale-2, so 0/negative is caught by the pairing rule; state gate outranks pairing; record at 200 — `routes/evidence.py:114-128`
- §3.6 (provisional triggers) — **revise** — **mismatch** — added "a waste-in submission" to the re-derivation trigger list — `routes/evidence.py:105`
- §3.3 (RI create) — insert — ambiguity — both fields required; full default block; RI at 201 — `routes/ri.py:28-53`
- §3.3 (samples) — insert — ambiguity — body fields all required; **no RI-status gate** — a result may be attached even after approval, refreshing only `valid_sample_count`, never the frozen risk figures; 201, immutable — `routes/ri.py:60-86`
- §3.3 (submission) — insert — ambiguity — request declares no fields; `valid_sample_count` re-derived before the test; RI at 200 — `routes/ri.py:92-109`
- §3.3 (review) — insert — ambiguity — approval leaves `revision_round_count` alone; `review_note` not persisted; RI at 200 — `routes/ri.py:117-132`
- §3.4 (alternatives) — insert — ambiguity — seven required fields; **no RI-status gate**; scored against `action_level_exceeded` as it stands at creation; alternative at 201 — `routes/ri.py:139-171`
- §3.5 (ROD draft) — insert — mismatch-adjacent ambiguity — cited RI must belong to the same site (`ERR_REMEDIAL_INVESTIGATION_NOT_FOUND`); **drafting is not gated on RI approval**; comment-window and signature fields start empty; 201 — `routes/rod.py:24-50`
- §3.5 (comment period) — insert — ambiguity — no body fields; document at 200 — `routes/rod.py:56-72`
- §3.5 (comment filing) — insert — ambiguity — **no actor-identity check** on a `PRPRepresentative` commenter; both fields required non-empty and not persisted; returns the **document** at 200 — `routes/rod.py:77-93`
- §3.5 (signature guards) — insert — ambiguity — the 60-point bar reads the *citing* investigation's flag; `ERR_REMEDY_NOT_PROTECTIVE` outranks `ERR_ALTERNATIVE_NOT_FOR_SITE` — `routes/rod.py:107-117`
- §3.5 (signature effects) — insert — ambiguity — **no phase gate on signature**: from any non-deleted phase other than the two named it succeeds and leaves `listing_status` untouched; document at 200 — `routes/rod.py:139-146`
- §3.7 (oversight billing) — insert — ambiguity — `incurred_cents` required non-negative (0 accepted), all three fields required, deleted site → `ERR_SITE_PHASE_INVALID`, and **the posting is not an addressable resource so `data` holds the site at HTTP 200** — `routes/sites.py:83-109`
- §3.8 (five-year review inputs) — insert — ambiguity — three required fields, `review_summary` not persisted; an empty `five_year_review_due_at` also reports `ERR_FIVE_YEAR_REVIEW_NOT_DUE`; site at 200 — `routes/sites.py:116-126`
- §3.8 (branches) — insert — **mismatch** — pinned the undeclared fourth combination (`PROTECTIVE_SHORT_TERM` + `deletion_recommended` true → `ERR_INVALID_STATE_TRANSITION`), the error id for a non-square ledger, and the **ordering inversion**: this endpoint tests the branch *after* the phase and due-date gates — `routes/sites.py:123-135`
- §2.6 item 10 — insert — **mismatch** — recorded the one ladder exception so §2.6 and §3.8 do not contradict — `routes/sites.py:123-135`
- §3.8 (PROTECTIVE cascade) — **revise** — ambiguity — "the site's contract" → **every** contract in `CONSTRUCTION_COMPLETE`; runs on any `PROTECTIVE` determination whether or not deletion was recommended; moves no ledger figure — `routes/sites.py:141-147`
- §4 table — revise ×2 — `/sites/{id}/oversight-costs` now states `data` holds the site; `/sites/{id}/records-of-decision` no longer claims the cited investigation must be approved

## Already fully pinned in this partition
Path-resolution error ids and left-to-right order (`routes/common.py:13-67`); the frozen/restricted/state/phase gate helpers and their §2.6 priorities; `new_record` id/seq/created_at/version semantics; the 201-vs-200 rule; the clock endpoint; the risk-assessment arithmetic, NPV/cost/remedy scoring and the selector tie-break chain; the de minimis eligibility conjunction; the indirect-rate tiers and prospective cap test; `effective_volume_tons` as a rule; hops 2 and 3 of the verification cascade; the `NOT_PROTECTIVE` three-hop cascade; the amended-signature withdrawal cascade.

No pass-1 edit was found to contradict impl.

## Step 9: Complete PRD — pass 3 of 3 (negotiation/execution/recovery routes + reads) — 2026-09-04T14:02:36.186304047Z

**Note on execution:** this pass was interrupted mid-run by a transient API error after it had already committed a large batch of edits (file had grown to 145,323 chars). Rather than respawning a fresh agent — which would not know which of its own edits had landed and would risk duplicate inserts — the orchestrator resumed the SAME agent via SendMessage with its context intact, instructing it to grep for distinctive wording before re-editing anything uncertain. It then completed normally.

## Counts
before pass 3: 542 lines / 130,549 chars → after: **542 lines / 145,365 chars**. Zero new lines; every patch an in-paragraph insert or in-place revision. Tail confirmed at the final §5 row.

**57 changes: 53 ambiguity-pins, 4 mismatch-revisions.**

## Mismatch-revisions
- **§2.3** — revise — the blanket filter sentence claimed the decision-document and contract lists accept `status`; two *nested* lists accept no filter at all. Rewritten to name the five filterless nested lists and to say a supplied filter is ignored — `routes/reads.py:196,286`
- **§3.6** — revise — "a site has at most one adopted round" is unenforced: an `ADOPTED` round is never superseded, so two can co-exist and `adopted_round_id` resolves to the **highest `round_number`** — `derive.py:447-454`, `routes/rounds.py:88`
- **§3.7** — revise — "A site has at most one entered instrument at a time" is unenforced: with two `ENTERED` the governing cap is the **earlier-created**, the later entry moving utilisation not at all — `derive.py:149-155`, `routes/decrees.py:110`
- **§3.8** — revise — pass 2's stewardship text said the five-year review is "uniquely" the endpoint whose transition check runs last; after the §2.6 clause was extended to two endpoints that became self-contradictory, so it now reads "one of the two exceptions §2.6 records" — `routes/sites.py:113-151`, `routes/decrees.py:137-144`

## Ambiguity-pins — cross-cutting consequences
- §2.3 — every list reaches the §2.3 defaults/bounds through one path and none bypasses it; the zero-or-one selected-remedy read is paginated on the same terms — `routes/reads.py:14,21,244`
- §2.3 — `limit`/`offset` and filter values are validated *ahead* of path resolution, so a bad `limit` on a list nested under a missing id is 422 not 404 — `routes/reads.py:31-33`
- §2.3 — single-resource reads and the cost-ledger projection are not lists, take no `limit`/`offset`, carry no pagination `meta` — `routes/reads.py:342`
- §2.3 — the site list's reversed primary key means records tied on `created_at` *and* `name` place the **later**-created first — `routes/reads.py:38-39`
- §2.3 — the `start_date` and owning-party keys are scoped to the site-scoped chain of title and the round's own share list; the *party*-scoped ownership-period list and the party-scoped share list keep plain `created_at` asc — `derive.py:43-46,77-79`
- §2.4 — the version bump is settled before the response renders, so a successful write returns the **new** `version` and refreshed `updated_at` — `routes/common.py` `respond()`
- §2.6 item 10 — revise — **extended** pass 2's ladder-exception clause from "One endpoint departs" to "Two endpoints depart": a compliance event tests the compliance dimension's transition after both the phase gate and the entry gate, so `ERR_SITE_PHASE_INVALID` and `ERR_DECREE_NOT_ENTERED` outrank `ERR_INVALID_STATE_TRANSITION` — `routes/decrees.py:137-144`
- §2.7 — these are the only two endpoints that take a version field, supplying one elsewhere has no effect, and a non-integer version is 422 at shape, decided before the path resolves and so before the 412 is reachable — `routes/rounds.py:31`, `routes/actions.py:31`

## Ambiguity-pins — §3.6 `routes/rounds.py`
- a new round's `accept_share_pct`, three percentage totals, `share_count`, `balloted_count`, `adopted_at`, `revision_note` initial values; create declares no state precondition; round at 201 — `rounds.py:87-118`
- the surviving weights can themselves sum to zero (denominator 0, every raw share 0.00, the whole 100.00 residual to one party) — `calc.py` `allocation_pcts`
- `ERR_NO_ALLOCATION_BASIS` is not re-applied at adoption — `rounds.py:140-150`
- a waste-in *submission* also re-derives provisionals; an evidentiary re-derivation that finds no basis writes 0.00 rather than raising — `derive.py:306-311`
- the balloting-open transition declares no fields, re-derives nothing, round at 200; both failure modes report the one `ERR_INVALID_STATE_TRANSITION` — `rounds.py:121-135`
- ballot identity is tested by locating *this round's* share for the acting id, so a party with no share here gets `ERR_ACTOR_IDENTITY_MISMATCH`, never a 404; `ballot_rationale` optional, empty when omitted — `rounds.py:160-166`
- adoption's two carve-outs are exhaustive: every other share goes `ALLOCATED`, including `NOTIFIED` and already-`SETTLED` parties; no share left `PENDING` — `derive.py:333-352`
- reopening's `revision_note` is required non-empty and overwrites any earlier note; late-added parties minted with the same empty ballot/percentage/`PENDING` fields — `rounds.py:178-195`
- reopening carries no posture gate and re-applies neither the normalisation nor the basis test; round at 200 — `rounds.py:178-198`

## Ambiguity-pins — §3.7 `routes/decrees.py`
- every remaining field of a fresh instrument at its zero/empty; drafting gated by nothing beyond the terminal phase; instrument at 201 — `decrees.py:40-68`
- lodging declares no fields, so an absent/empty body is well formed; instrument at 200 — `decrees.py:74,93`
- `court_docket_number` is the one field entry declares, required and non-empty — `decrees.py:99-100`
- entry leaves every penalty figure otherwise untouched; instrument at 200 — `decrees.py:113-120`
- `violation_type` and `paid_penalty_cents` are optional on **every** event type, validated whenever supplied then discarded where the type has no use for them — `decrees.py:133-134`
- an inadmissible event type against a never-entered instrument reports `ERR_DECREE_NOT_ENTERED`; every accepted event returns the **instrument** at 200 — `decrees.py:137-144,188`
- a `VIOLATION` stamps `violation_type` empty when omitted and overwrites what an earlier violation recorded — `decrees.py:148`
- both of the assessment's temporal preconditions report `ERR_INVALID_STATE_TRANSITION`, not a temporal error id — `decrees.py:151-159`
- an omitted `paid_penalty_cents` is read as 0 on a cure — `decrees.py:177`
- the cure's `open_violation_count` decrement is floored at 0 — `decrees.py:185`
- a cure leaves `accrued_penalty_cents`, `penalty_capped` and `violation_type` standing — `decrees.py:180-185`

## Ambiguity-pins — §3.8 `routes/contracts.py`
- both solicitation fields required non-empty; a ROD under another site reports `ERR_RECORD_OF_DECISION_NOT_FOUND` — `contracts.py:32-36`
- the solicitation carries no phase or posture gate beyond the terminal one — `contracts.py:37`
- `punch_list_items` starts at 0 — `contracts.py:50`
- `max_concurrent_windows` already reads the default 2 **from creation**, is never null, and is only overwritten by an award that states a value; contract at 201 — `contracts.py:48,52,68`
- `contractor_name` required non-empty — `contracts.py:63`
- `awarded_amount_cents` is non-negative, so a bid of exactly 0 is well formed — `contracts.py:64`
- `max_concurrent_windows` optional on award; omitted leaves the field alone — `contracts.py:65,84-86`
- the phase advance is conditional on the site standing in `ROD_SIGNED`; the award itself has no phase gate; contract at 200 — `contracts.py:87-93`
- a window's `description` is optional, non-empty when supplied, empty when omitted — `contracts.py:110`
- `end_at` after `start_at` is a priority-3 **shape** rule decided before the contract path resolves, so a reversed interval against a missing contract is 422 not 404 — `contracts.py:112-115`
- scheduling declares **no** precondition on the contract's own `status` — `contracts.py:116-125`
- `work_window_count` is re-derived rather than incremented and is stored, so an accepted window bumps the **contract's** version; window at 201 with no `updated_at`/`version` — `contracts.py:140,145`, `serialize.py:315`
- `punch_list_items` is the one field completion declares, a required non-negative integer — `contracts.py:154`
- only the phase advance is conditional on `CONSTRUCTION`; `construction_complete_at` and `five_year_review_due_at` are stamped and eligible instruments terminated unconditionally — `contracts.py:162-169`
- completion returns the **contract** at 200; the site's stamps read back from their own endpoints — `contracts.py:172`

## Ambiguity-pins — §3.9 `routes/actions.py`
- `claimant_prp_id` is optional on **every** type, stored only for `CONTRIBUTION_CLAIM`, otherwise body-ref-checked then discarded; need not be of this site nor differ from the respondent — `actions.py:32,35,69-71`
- creation returns the **action** at 201; response, collection and voiding each return the **action** at 200 — `actions.py:95,147,177,223`
- the respondent's share must be `ALLOCATED`, so a settled or orphaned share is refused — `actions.py:45-51`
- a cross-site respondent is refused `ERR_RESPONDENT_NOT_ALLOCATED`, the only place a wrong-site reference is not a 404 — `actions.py:47-51`
- `respondent_share_pct_at_offer` is captured on every type (0.00 when `final_pct` is unset), unlike `premium_floor_cents` — `actions.py:53,75`
- `response_note` optional and not persisted; accepting a de minimis settlement **re-tests** both issuance gates against current data, and neither re-test applies to a rejection or the other two types — `actions.py:119-133`
- acceptance sets `status`/`contribution_protection` unconditionally while the share half is conditional on a surviving adopted round and an `ALLOCATED` disposition; the round's three totals are re-derived, not adjusted — `actions.py:98-112`
- `ACCEPTED`-or-partially-collected is one precondition; `received_cents` non-negative so 0 is legal; `receipt_reference` validated then not persisted — `actions.py:154-158`
- `void_reason` is the one field voiding declares — `actions.py:184`
- voiding leaves `received_at`, `demanded_cents`, `premium_floor_cents` and `respondent_share_pct_at_offer` standing — `actions.py:196`
- both void restorations are conditional on the grant still standing, and a `CONTRIBUTION_CLAIM` void mirrors no grant at all — `actions.py:198-221`

## Already fully pinned
The Gore-factor arithmetic and its rescaling/residual rules, the two record-set variants, the 66.67 adoption threshold with equality adopting, round numbering across superseded rounds, the candidate set, the penalty accrual/cap/idempotent-recompute rules, the buffered-interval derivation and the concurrency test, the de minimis premium-floor formula and its freezing, overpayment refusal, the ledger conservation identity, and every ordering key `derive.py` states explicitly.

## Completeness statement
The paging question is answered and pinned: **no read endpoint bypasses §2.3** — all thirty-odd lists take `shape.pagination()` and feed `common.paged`, and `common.listing` (`routes/common.py:138-143`) is dead code. **No pass-1 or pass-2 edit contradicts the implementation**; the only earlier-pass text touched was pass 2's "uniquely" wording, made stale by the §2.6 extension.

After three passes every behavior in `implementation/` is traceable to a `PRD_COMPLETED.md` sentence, with two deliberate exceptions left under-determined rather than pinned:
1. `common.listing` is unused, so nothing in the PRD describes it — correctly, since it produces no observable behavior.
2. Field **order** inside `data` is not pinned anywhere; JSON object order is not a contract and pinning it would over-specify.

## Pipeline complete — 2026-09-04T14:02:36.186304047Z

**Orchestrator final verification:**
- `PRD_COMPLETED.md` is 542 lines / 145,365 chars and differs from `PRD_FINALIZED.md` in 158 lines — NOT byte-identical, so the scan demonstrably ran (3 passes, 109 total changes: 92 ambiguity-pins, 13 mismatch-revisions, plus the 4 late mismatch-revisions of pass 3).
- Tail ends at the final §5 error-code table row; all 28 headings and all 49 error rows intact.
- Document chain: `PRD.md` 536 lines/107,754 chars → `PRD_FINALIZED.md` 536/109,709 → `PRD_COMPLETED.md` 542/145,365.
- No file under `implementation/`, `test_suite/`, or `test_helpers/` was modified after the 12:30 green sweep, so the 8×142/142 result still describes the shipped artifact.
- Exactly one `worklog.md`, at the task root; no stray copies under `workspace/`, no leftover `.bak`/report files. `test_helpers/` and `test_suite/` are at the task root as required.
